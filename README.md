# Industrial Safety Compliance Standards Q&A

A citation-grounded RAG system for functional-safety and machine-safety standards used
in industrial automation (IEC/ISO/DIN-class standards such as IEC 61508, IEC 62061,
ISO 13849-1, and their US-analogues like OSHA 1910). It answers *"what are the safety
requirements for X"* with precise clause-number citations, refuses to answer when no
source clause supports the claim, and routes every uncertain or contradicted claim
through an automated LLM-judge check before a human ever needs to look at it — and to a
human review queue when the judge itself is unsure.

## Problem statement

Industrial automation engineers (control system design, functional safety, machine
safeguarding — the kind of work that sits behind PLCs, drives, and safety
relays/controllers) constantly need to answer questions like *"what's required for an
emergency stop category on this machine?"* or *"what SIL/PL does this safety function
need?"*. The source of truth — IEC/ISO/DIN safety standards — is long, cross-referenced,
often paywalled in full, and getting the clause wrong has real consequences: a missed
or misapplied requirement is a safety defect, not a cosmetic bug.

A generic LLM chatbot is the wrong tool here: it will answer fluently and confidently
whether or not it actually knows the clause, and a wrong-but-confident answer in this
domain is worse than no answer. The problem this project solves is not "can an LLM
answer safety questions" — it's **"can we build a system that only ever answers with a
claim it can point to a real clause for, and that catches itself (and gets a human to
catch it) when it can't."**

## Introduction to the problem and methodology

Retrieval-Augmented Generation (RAG) is a natural fit for regulated, citation-heavy
domains because it separates *what the model knows* from *what the source document
says*, and lets you check the model's output against the latter mechanically. But a
naive RAG pipeline (retrieve chunks → ask the LLM to answer with the chunks in context)
still lets the model paraphrase loosely, cite the wrong clause, or quietly drop the
"I don't know" case in favor of a plausible-sounding guess. None of that is acceptable
in a safety-compliance setting.

This project's methodology treats grounding as something to be **verified, not
assumed**:

1. The corpus is ingested at **clause granularity** (not page or paragraph), so every
   retrievable unit maps to a citable clause number.
2. The generator is never allowed to return prose — it returns a **list of discrete,
   independently-checkable claims**, each with a citation and a verbatim quote, or an
   explicit "unsupported" marker when nothing in the corpus backs it.
3. A first LLM judge **re-checks every claim against the real clause text**
   (independently of the generator's own reasoning) and labels it supported,
   contradicted, or unsupported.
4. A second LLM judge takes anything that isn't cleanly "supported" and packages it into
   a ranked review item for a **human-in-the-loop (HITL)** reviewer, who can approve,
   edit, or reject it.
5. Only claims that pass the judge — or pass a human after review — ever reach the
   end user.

Full architecture and the phase-by-phase build plan are in
[`artifacts/system-arch-and-roadmap.md`](artifacts/system-arch-and-roadmap.md).

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
| **Corpus scoping** | Restrict to legitimately public, clause-numbered excerpts (OSHA 1910/1926, public IEC/ISO front-matter, freely-viewable NFPA editions, etc.) — full paywalled standard text is explicitly out of scope. See the architecture doc for the licensing breakdown. |
| **Clause-aware ingestion** | Parse and chunk source documents at clause boundaries, preserving `standard → clause path → text` structure so every chunk is independently citable. |
| **Hybrid retrieval** | BM25 (for literal clause-number/term matches) + dense embeddings (for semantic recall), combined via reciprocal rank fusion. |
| **Grounded generation** | LLM answers only from retrieved chunks, output constrained to a structured schema: `{claim, citation, verbatim quote}` or `unsupported`. |
| **Judge 1 — Grounding & Contradiction** | Independent LLM call re-checks each claim's quote against the actual corpus clause text; verdict is `supported` / `contradicted` / `unsupported`. |
| **Judge 2 — Escalation** | Packages every non-`supported` verdict into a ranked, de-duplicated review item for a human reviewer. |
| **HITL review** | Human approves, edits, or rejects each flagged claim; every decision is logged for audit and feeds the eval/regression set. |
| **Answer assembly** | Final answer = judge-supported claims + human-cleared claims only, each still carrying its citation. |
| **Evaluation** | Retrieval recall@k, citation precision, judge precision/recall on an adversarial set, and refusal correctness are tracked as first-class metrics. |

## Project repo

```
Industrial-safety-compliance-standards-Q-A/
├── README.md                              # this file
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
│   └── judging/                           # Phase 4: Judge 1, grounding & contradiction (done)
│       ├── schema.py                      # Pydantic: ClaimVerdict / GroundingJudgeOutput
│       ├── prompt.py                      # independent judge system + user prompt
│       ├── grounding_judge.py             # deterministic re-check + batched semantic LLM judgment
│       ├── eval_set.py                    # adversarial claims (hallucinated citations, altered quotes, contradictions)
│       └── run_judge_eval.py              # CLI: python -m safety_qa.judging.run_judge_eval (needs ANTHROPIC_API_KEY)
│   └── review/                            # Phase 5+6: Judge 2 + HITL + feedback loop (done)
│       ├── escalation.py                  # Judge 2: severity-ranked escalation packets (no LLM)
│       ├── store.py                       # persistent review queue (separate DB from corpus.db)
│       ├── assembly.py                    # final answer = supported + HITL-cleared claims
│       ├── cli.py                         # CLI: python -m safety_qa.review.cli (work the queue)
│       ├── pipeline.py                    # CLI: python -m safety_qa.review.pipeline "question" (full loop)
│       ├── regression.py                  # overturned-case extraction + judge-override-rate metric
│       └── run_regression.py              # CLI: python -m safety_qa.review.run_regression (needs ANTHROPIC_API_KEY)
└── tests/
    ├── test_ingestion.py
    ├── test_retrieval.py
    ├── test_generation.py
    ├── test_judging.py
    ├── test_review.py
    └── test_regression.py
```

Hardening (Phase 7) lands under this structure per the phase plan in
[`artifacts/system-arch-and-roadmap.md`](artifacts/system-arch-and-roadmap.md) — that
document is the source of truth for what gets built in what order.

**Status:**
- **Phase 1** (clause-aware ingestion) — done. 135 clauses of 29 CFR 1910.147 parsed
  from raw eCFR XML into a queryable SQLite store, each independently addressable by a
  canonical citation key (`OSHA-1910.147#(c)(4)(i)`), with notes/appendix content
  correctly marked non-normative.
  Run: `PYTHONPATH=src python -m safety_qa.ingestion.run_ingest`
- **Phase 2** (hybrid retrieval) — done. BM25 (hand-rolled, stemmed) + **e5-base-v2**
  neural sentence embeddings (local, via `sentence-transformers` — no API key,
  runs on GPU if available) fused via reciprocal rank fusion. **recall@5 = 100%**
  (15/15) on the golden set, up from 93.3% under the original TF-IDF/LSA semantic
  leg — that earlier choice was made when a real embedding model looked like it'd
  need either an API key or a heavy install; once torch/transformers turned out to
  already be present with GPU support, the trade-off no longer held, so the leg was
  swapped (see CHG-20260911-06 in `artifacts/changelogs.md`). The one previously
  documented limitation (a definition losing to other definitions that
  cross-reference it, on pure lexical frequency) is resolved under real embeddings.
  Run: `PYTHONPATH=src python -m safety_qa.retrieval.run_eval`
  Inspect raw retrieval for any question: `PYTHONPATH=src python -m safety_qa.retrieval.ask "your question"`
- **Phase 3** (grounded generation) — done. First phase that calls an actual LLM
  (Claude, via structured tool-use output). The generator only sees retrieved
  clauses (no open-book knowledge) and must emit discrete, independently-checkable
  claims — each with a citation and a verbatim quote — or explicitly flag anything
  the corpus doesn't cover in `unsupported_aspects`, instead of guessing. Every claim
  is then re-checked deterministically before being trusted: cited clause must
  actually be among what was retrieved (catches hallucinated citations), and the
  quote must be an exact substring of that clause's text (catches paraphrasing
  disguised as quoting) — anything that fails either check is dropped into
  `rejected_claims` with a reason, never silently shown as an answer. This is a
  cheap sanity floor, not a replacement for Phase 4's semantic grounding judge.
  All 9 tests run against a fake, deterministic LLM client — no network call, no API
  key needed for CI.
  Real usage needs `export ANTHROPIC_API_KEY=...`, then:
  `PYTHONPATH=src python -m safety_qa.generation.ask "your question"`
- **Phase 4** (Judge 1 — Grounding & Contradiction) — done. Two layers, matching the
  arch doc exactly: (1) an independent deterministic re-check — every claim's cited
  clause is re-fetched straight from the corpus by its own DB lookup (never reusing
  Phase 3's chunk objects) and its quote re-verified verbatim from scratch; a claim
  failing this is `unsupported` with zero LLM calls. (2) everything that clears step 1
  goes into one **batched** LLM call (cost-conscious per the arch doc's Sec 4.4 note)
  asking the question string-matching can't: does the clause actually *entail* the
  claim, or does the claim misrepresent/contradict it (e.g. clause says "at least
  annually", claim says "monthly" — verbatim-valid quote, wrong claim).
  All 10 tests cover the deterministic layer and the LLM-layer plumbing (batching,
  claim_id-based response mapping, retry-once-then-fail) against a fake client — zero
  API key needed for CI. What genuinely can't be tested without a live model: whether
  the judge actually *catches* a contradiction. For that, `judging/eval_set.py` has a
  9-case adversarial set (correct claims, contradicted claims, hallucinated citations,
  altered quotes) with expected verdicts; run it against a real model with
  `export ANTHROPIC_API_KEY=...` then `PYTHONPATH=src python -m safety_qa.judging.run_judge_eval`
  for a precision/recall report — this one isn't CI-enforced the way Phase 2's recall@k
  is, since there's no dependency-free way to check semantic judgment quality.
- **Phase 5** (Judge 2 — Escalation + HITL review) — done. Judge 2 makes zero LLM
  calls (a deliberate choice): severity-ranking (`contradicted` outranks
  `unsupported`) and deduping a flagged claim against an already-pending item are
  mechanical, not judgment calls. Escalated claims go into a **separate** SQLite
  queue (`review_queue.db`, not `corpus.db` — the queue holds real human-decision
  history that must never share a file with something `run_ingest` can rebuild).
  A CLI (`review/cli.py`) lets a reviewer approve/edit/reject each item with a
  required rationale, fully audited (every decision logged, `review_item.status`
  always reflects the latest one). Final-answer assembly combines Judge
  1's `supported` claims with HITL-cleared ones — pending and rejected claims are
  held back, never shown as if they were checked. Validated live (not just
  against fakes): a real Kimi Judge 1 call correctly flagged a deliberately wrong
  claim as `contradicted`, Judge 2 built the escalation packet, the claim was
  correctly excluded before review and correctly excluded again after a simulated
  reject decision. 16 new tests, all deterministic (no LLM dependency for this
  phase at all).
  Full loop: `PYTHONPATH=src python -m safety_qa.review.pipeline "your question"`
  Work the queue: `PYTHONPATH=src python -m safety_qa.review.cli`
- **Phase 6** (feedback & regression harness) — done. `review/regression.py`
  extracts every case where a human overturned Judge 1 (approved or edited a
  claim Judge 1 had flagged) and computes the judge-override rate — how often a
  human disagreed with Judge 1, the real-world precision metric. `run_regression.py`
  replays each overturned case through a fresh Judge 1 call to catch prompt
  drift ("this exact claim must not come back wrongly flagged"), but **only**
  for cases Judge 1's own LLM judgment originally caught — a case caught by the
  deterministic layer (hallucinated citation, non-verbatim quote) is a pure
  string/lookup check that will reproduce identically forever unless the corpus
  itself changes, so replaying it through a model tests nothing and would just
  spend an API call for no signal. This distinction (`judge1_source` on every
  review item) was added mid-build after running real data through the system
  and finding the first version of the replay logic would have mislabeled a
  deterministic catch as a "regression."
  Seeded with real (not synthetic) review history to build this against:
  3 organic real questions produced zero escalations — a real, honest signal
  Judge 1 was already precise — so 3 deliberately-wrong claims were run through
  the live pipeline instead; 2 were genuinely correct catches (confirmed via
  reject), 1 was a genuine transcription error in the quote (fixed via edit) —
  giving a real override rate of 33% (1/3) to validate the harness against.
  6 new tests, all deterministic (the pure extraction/metric logic; the live
  replay is validated manually, same honest limitation as Phase 4's eval).
  Run: `PYTHONPATH=src python -m safety_qa.review.run_regression`

Tested throughout: `pytest` (77 tests, all passing, zero requiring live API access).
