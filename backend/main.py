"""The deployed web app -- wraps the existing pipeline (retrieval, generation,
Judge 1, Judge 2/HITL) behind an HTTP API, with PostgreSQL replacing the CLI
tools' SQLite files as the storage backend. None of the core pipeline logic is
reimplemented here; this module is wiring, not a second copy of the system.

    PYTHONPATH=src:. uvicorn backend.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from safety_qa.generation.generator import GenerationError, Generator
from safety_qa.generation.llm_client import build_client
from safety_qa.judging.grounding_judge import GroundingJudge
from safety_qa.review.assembly import assemble_final_answer
from safety_qa.review.escalation import build_packets
from safety_qa.retrieval.chunking import build_chunks
from safety_qa.retrieval.retriever import Retriever

from . import corpus_store, review_store
from .db import init_schema, make_engine
from .ingest import run as run_ingest
from .schemas import AskRequest, AskResponse, ClaimOut, DecisionRequest, HealthResponse, ReviewItemOut

_STANDARD_ID = "OSHA-1910.147"
_STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = make_engine()
    init_schema(engine)
    if corpus_store.corpus_is_empty(engine, _STANDARD_ID):
        run_ingest()  # first boot against a fresh database: ingest automatically
    app.state.engine = engine

    clauses = corpus_store.list_clauses(engine, _STANDARD_ID)
    chunks = build_chunks(clauses)
    app.state.retriever = Retriever(chunks)  # built once -- loads the embedding model a single time, not per request

    yield


app = FastAPI(title="Industrial Safety Compliance Q&A", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(str(_STATIC_DIR / "index.html"))


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    clauses = corpus_store.list_clauses(app.state.engine, _STANDARD_ID)
    return HealthResponse(status="ok", corpus_loaded=len(clauses) > 0, clause_count=len(clauses))


@app.post("/api/ask", response_model=AskResponse)
def ask(request: AskRequest) -> AskResponse:
    """The full pipeline: retrieve -> generate -> judge -> escalate -> assemble.
    Same policy as review/pipeline.py's default mode: ships supported +
    already-cleared claims immediately, holds back anything newly flagged for a
    human rather than blocking the request on it."""
    engine = app.state.engine
    retriever: Retriever = app.state.retriever

    generator = Generator(retriever, build_client("generator"))
    try:
        generation_result = generator.answer(request.question)
    except GenerationError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    clause_lookup = lambda standard_id, path: corpus_store.get_clause_by_path(engine, standard_id, path)  # noqa: E731
    judge = GroundingJudge(None, build_client("judge"), clause_lookup=clause_lookup)
    judged = judge.evaluate(generation_result)

    review_store.log_verdicts(engine, judged.judged_claims, judged.query)

    packets = build_packets(judged)
    claim_id_to_item_id = review_store.enqueue_all(engine, packets)

    final = assemble_final_answer(
        judged, None, claim_id_to_item_id,
        get_item_fn=lambda item_id: review_store.get_item(engine, item_id),
    )
    return AskResponse(
        query=final.query,
        claims=[
            ClaimOut(text=c.text, standard_id=c.citation.standard_id, clause=c.citation.clause, quote=c.citation.quote)
            for c in final.claims
        ],
        pending_count=final.pending_count,
        rejected_count=final.rejected_count,
        unsupported_aspects=final.unsupported_aspects,
    )


@app.get("/api/queue", response_model=list[ReviewItemOut])
def list_queue() -> list[ReviewItemOut]:
    items = review_store.list_pending(app.state.engine)
    return [
        ReviewItemOut(
            id=i.id, query=i.query, claim_text=i.claim_text, standard_id=i.standard_id, clause=i.clause,
            quote=i.quote, judge1_verdict=i.judge1_verdict, judge1_reasoning=i.judge1_reasoning,
            severity=i.severity, created_at=i.created_at,
        )
        for i in items
    ]


@app.post("/api/queue/{item_id}/decision")
def submit_decision(item_id: int, decision: DecisionRequest) -> dict:
    item = review_store.get_item(app.state.engine, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="review item not found")
    try:
        review_store.record_decision(
            app.state.engine, item_id, decision.reviewer_id, decision.action, decision.rationale,
            edited_text=decision.edited_text, edited_quote=decision.edited_quote,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"status": "recorded"}
