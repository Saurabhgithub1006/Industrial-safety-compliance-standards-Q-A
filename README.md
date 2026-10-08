# Industrial Safety Compliance Standards Q&A

A citation-based RAG system for functional and machine safety standards in industrial automation (IEC/ISO/DIN-class standards such as IEC 61508, IEC 62061,
ISO 13849-1, and their US-analogues like OSHA 1910). It provides safety requirements with exact clause citations, avoids unsupported answers, and sends uncertain or conflicting claims for automated checking and human review.

## Problem statement

Industrial automation engineers often need quick answers about safety requirements for machines, PLCs, drives, and safety controllers. Safety standards are long, cross-referenced, and sometimes paywalled, and using the wrong clause can cause serious safety issues.

A generic LLM may give confident but incorrect answers. This project focuses on providing answers only when they are supported by real standard clauses, while sending uncertain answers for automated and human review.

## Introduction to the problem and methodology

RAG is useful for safety standards because it connects the LLM’s answers directly to source documents. However, a basic RAG system can still give wrong clauses or make unsupported guesses.

This project ensures that every answer is **verified before reaching the user**:

1. Standards are stored at the **clause level** for accurate citations.
2. The system generates separate claims with citations and quotes, or marks them as **unsupported**.
3. An LLM judge checks each claim against the original clause.
4. Unclear or incorrect claims are sent for **human review**.
5. Only verified claims are shown to the user.

 
## Objective

Build and demonstrate a working system that:

- Answers automation-safety questions with **clause-level citations**, not paraphrased summaries.
- **Refuses rather than hallucinates** when the corpus has no supporting clause.
- Has an **automated grounding/contradiction judge** that checks every claim's citation against the actual source text before it's trusted.
- Escalates anything the judge flags to a **human review workflow** with a full audit trail (who approved/edited/rejected what, and why).
- Reports **quantitative evaluation metrics** (retrieval recall, citation precision, judge precision/recall, refusal correctness) so the system's rigor is demonstrable, not just claimed.

## Core methodology

| Stage | What it does |
|---|---|
| **Corpus scoping** |The system will only use **publicly available, clause-numbered excerpts**, such as OSHA 1910/1926 and freely available IEC/ISO or NFPA content. Full paywalled standards are outside the project scope. The licensing details are covered in the architecture document.|
| **Clause-aware ingestion** | Source documents are divided by clause boundaries while keeping the standard, clause path, and text together. This makes each chunk easy to cite independently. |
| **Hybrid retrieval** |Use BM25 for exact clause and keyword matches, and dense embeddings for semantic matches. Combine both results using Reciprocal Rank Fusion (RRF) for better retrieval.|
| **Grounded generation** | The LLM answers only from the retrieved chunks and follows a fixed structure: **claim, citation, and verbatim quote**, or **unsupported** when no evidence is found.|
| **Judge 1 : Grounding & Contradiction** | An independent LLM checks each claim against the original clause text and marks it as **supported, contradicted, or unsupported**.|
| **Judge 2 : Escalation** | Any claim that is not **supported** is grouped into a ranked, duplicate-free review item for human review. |
| **HITL review** | Human approves, edits, or rejects each flagged claim; every decision is logged for audit and feeds the eval/regression set. |
| **Answer assembly** | Final answer = judge-supported claims + human-cleared claims only, each still carrying its citation. |
| **Evaluation** |The system tracks retrieval recall@k, citation precision, judge precision/recall, and refusal accuracy using an adversarial test set. |

## Project repo

```
Industrial-safety-compliance-standards-Q-A/
├── README.md                              # this file
├── DEPLOY.md                              # step-by-step Fly.io deployment guide
├── Dockerfile                             # bakes the embedding model in at build time
├── fly.toml                               # Fly.io app config
├── LICENSE
├── pyproject.toml
├── artifacts/
│   └── system-arch-and-roadmap.md         # full architecture + phase-wise build roadmap
├── data/
│   ├── raw/                               # unmodified source documents + SOURCES.md provenance
│   └── processed/                         # generated (SQLite corpus.db) -- gitignored, rebuild with run_ingest
├── src/safety_qa/
│   ├── ingestion/                         # Phase 1: clause-aware parsing + storage (done)
│   │   ├── canonical.py                   # citation_key normalization
│   │   ├── models.py                      # Standard / Clause data model
│   │   ├── parser_osha_ecfr.py            # eCFR-XML -> clause tree parser
│   │   ├── store.py                       # SQLite persistence
│   │   └── run_ingest.py                  # CLI: python -m safety_qa.ingestion.run_ingest
│   ├── retrieval/                         # Phase 2: hybrid retrieval (done)
│   │   ├── chunking.py                    # Clause -> retrievable Chunk
│   │   ├── bm25.py                        # hand-rolled Okapi BM25 (lexical leg)
│   │   ├── stemming.py                    # zero-dependency Porter stemmer
│   │   ├── semantic.py                    # e5-base-v2 neural embeddings (semantic leg, local, no API)
│   │   ├── hybrid.py                      # reciprocal rank fusion
│   │   ├── retriever.py                   # Retriever: ties both legs together
│   │   ├── eval_set.py                    # golden question -> clause set + recall@k
│   │   ├── run_eval.py                    # CLI: python -m safety_qa.retrieval.run_eval
│   │   └── ask.py                         # CLI: inspect raw retrieval for any question
│   ├── generation/                        # Phase 3: grounded generation (done)
│   │   ├── schema.py                      # Pydantic: Claim / Citation / GeneratedAnswer
│   │   ├── llm_client.py                  # LLMClient protocol: AnthropicClient + FakeLLMClient
│   │   ├── prompt.py                      # system + user prompt construction
│   │   ├── generator.py                   # retrieve -> prompt -> validate -> claims
│   │   └── ask.py                         # CLI: python -m safety_qa.generation.ask (needs ANTHROPIC_API_KEY)
│   ├── judging/                           # Phase 4: Judge 1, grounding & contradiction (done)
│   │   ├── schema.py                      # Pydantic: ClaimVerdict / GroundingJudgeOutput
│   │   ├── prompt.py                      # independent judge system + user prompt
│   │   ├── grounding_judge.py             # deterministic re-check + batched semantic LLM judgment
│   │   ├── eval_set.py                    # adversarial claims (hallucinated citations, altered quotes, contradictions)
│   │   └── run_judge_eval.py              # CLI: python -m safety_qa.judging.run_judge_eval (needs ANTHROPIC_API_KEY)
│   └── review/                            # Phase 5+6+7: Judge 2 + HITL + feedback loop + hardening (done)
│       ├── escalation.py                  # Judge 2: severity-ranked escalation packets (no LLM)
│       ├── store.py                       # review queue + judge_verdict_log (separate DB from corpus.db)
│       ├── assembly.py                    # final answer = supported + HITL-cleared claims
│       ├── cli.py                         # CLI: python -m safety_qa.review.cli --reviewer NAME (work the queue)
│       ├── pipeline.py                    # CLI: python -m safety_qa.review.pipeline [--wait --reviewer NAME] "question"
│       ├── regression.py                  # overturned-case extraction + judge-override-rate metric
│       └── run_regression.py              # CLI: python -m safety_qa.review.run_regression (needs ANTHROPIC_API_KEY)
├── backend/                                # deployed web app: FastAPI + PostgreSQL (done)
│   ├── main.py                             # FastAPI app -- wires the existing pipeline behind HTTP
│   ├── db.py                               # portable engine: sqlite:/// locally, postgresql:// in production
│   ├── models.py                           # SQLAlchemy Core table definitions
│   ├── corpus_store.py                     # corpus persistence, mirrors ingestion/store.py's interface
│   ├── review_store.py                     # review-queue persistence, mirrors review/store.py's interface
│   ├── ingest.py                           # auto-runs on first boot against an empty database
│   ├── schemas.py                          # API request/response models
│   └── static/index.html                   # the frontend -- ask a question, work the review queue
└── tests/
    ├── test_ingestion.py
    ├── test_retrieval.py
    ├── test_generation.py
    ├── test_judging.py
    ├── test_review.py
    ├── test_regression.py
    └── test_backend.py
```



**Status:**
- Phase 1: Clause-Aware Ingestion
The system parses 135 OSHA 1910.147 clauses from eCFR XML and stores them in a queryable database. Each clause has a unique citation key, making it easy to retrieve and cite the exact safety requirement.    
- Phase 2: Hybrid Retrieval
The system combines BM25 keyword search with e5-base-v2 embeddings for semantic search. Both results are combined using Reciprocal Rank Fusion (RRF). The system achieved 100% recall@5 (15/15) on the test set.    
- Phase 3: Grounded Generation
The LLM generates answers only from the retrieved clauses. Each claim must include a citation and a verbatim quote. If the available sources do not support a claim, it is marked as unsupported instead of generating a guess. The system also checks that the citation and quote actually match the retrieved clause.   
- Phase 4: Grounding and Contradiction Check
An independent judge checks each generated claim against the original clause. It verifies whether the clause actually supports the claim and identifies incorrect or contradictory statements. Each claim receives one of three verdicts: supported, contradicted, or unsupported.  
- Phase 5: Human Review
Claims that are contradicted or unsupported are sent to a separate review queue. A human reviewer can approve, edit, or reject these claims, with every decision recorded for auditing. Only supported or human-approved claims are included in the final answer.    
- Phase 6: Feedback and Regression Testing
The system records cases where human reviewers disagree with the judge and uses them for regression testing. This helps identify changes in judge performance and prevent previously detected issues from appearing again.    
- Phase 7: System Hardening
The final phase improved system monitoring and auditing. Judge decisions are logged with the model and prompt version, reviewer identity is required, and an optional review mode allows newly flagged claims to be reviewed before the final answer is returned.

## Post-Roadmap Optimizations

A targeted review of the completed system identified three concrete areas for improvement:

**1. Retry and Backoff:**  
Added automatic retries for temporary API errors, with increasing wait times of 5, 10, and 20 seconds. This improves reliability when API rate limits are reached.

**2. Prompt Caching:**  
Added prompt caching to the Anthropic client to reduce repeated processing. The Kimi client already supports automatic caching for repeated context.

**3. Improved Citation Rules:**  
Tightened citation rules to prevent the system from using a related clause as the definition of a term. This issue was identified during live testing and successfully caught by the judge.

6 new tests (5 for the retry helper, mocking `time.sleep` so they run instantly;
1 confirming the new prompt rule is actually sent). Live-validated: a real call
through the refactored `KimiClient` still works correctly end to end.

## Web Application

A deployed **FastAPI + PostgreSQL** web application was added to expose the same safety QA pipeline through an HTTP API instead of the CLI.

- Reuses the existing **retrieve → generate → judge → assemble** pipeline without duplicating the core logic.
- Uses **SQLAlchemy Core** for database storage, supporting SQLite for local development and PostgreSQL for production.
- Added **8 new tests** and completed a live end-to-end test through `POST /api/ask`.
- The live test successfully returned **3 grounded claims** for the query `"what is a lockout device?"`.
- The application is **containerized** with the embedding model included in the image and configured for **Fly.io deployment**.
- **101 automated tests** pass, with no tests requiring live API access.

See [`DEPLOY.md`](DEPLOY.md) for deployment instructions.
