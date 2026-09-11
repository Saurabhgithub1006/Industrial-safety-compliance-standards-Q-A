# Changelog

> Entries CHG-20260907-01 through CHG-20260909-05 are backfilled retrospectively on
> 2026-09-10, when `artifacts/skill.md`'s evidence-driven workflow was adopted for
> this project. They were not produced by that workflow in real time (it didn't
> exist yet during Phases 1-4) — content is reconstructed from the actual commits,
> test runs, and verified output already in the repo/session history, not from
> memory. CHG-20260910-06 onward follow the workflow live.

## CHG-20260907-01 — Clause-aware ingestion of 29 CFR 1910.147 — 2026-09-07

**What:** Built the Phase 1 ingestion pipeline: a parser that reconstructs the true clause hierarchy of an OSHA regulation from eCFR XML, a canonical citation-key scheme, and a SQLite store making every clause independently queryable by that key.

**How it works:** The source markup doesn't nest clauses as XML elements — a whole opening chain like `(a) Scope...—(1) Scope. (i) This standard covers...` lives in one flat `<P>` tag, and inline cross-references (`"see paragraph (c)(1)"`) reuse the identical bracket syntax. `parser_osha_ecfr.py` resolves this with a stack-based algorithm keyed on value succession, not punctuation: a sibling is the literal next value in its class's sequence (`iii`→`iv`, `4`→`5`); a new nested list always starts at its class's first value (`i`, `A`, `1`). `canonical.py` builds a `citation_key` (`OSHA-1910.147#(c)(4)(i)`) at ingest time so downstream citation matching is always exact, never fuzzy. Definitions (prose, not marker-numbered in the source) get synthetic keys by term slug; notes and the non-mandatory appendix are ingested but flagged `is_normative=False` so they're never presented as binding requirements.

**Result:** 135 clauses parsed from the real regulation, zero duplicate citation keys, every clause independently queryable by its key. 17 tests passing, including regression tests for three specific parsing bugs found and fixed against the live document (chain-continuation markers wrongly matching stale ancestors; the nesting cycle being 3-long after depth 1, not 4; a title containing its own parentheses breaking chain detection).

**Files:** `src/safety_qa/ingestion/canonical.py`, `models.py`, `parser_osha_ecfr.py`, `store.py`, `run_ingest.py`, `data/raw/osha_1910_147_raw.xml`, `data/raw/SOURCES.md`, `tests/test_ingestion.py`

---

## CHG-20260907-02 — Hybrid retrieval over the ingested corpus — 2026-09-07

**What:** Built Phase 2: BM25 + a local TF-IDF/LSA semantic leg, fused with reciprocal rank fusion, with no embedding API dependency.

**How it works:** `bm25.py` is a hand-rolled Okapi BM25 implementation (zero dependency). `semantic.py` uses TF-IDF + truncated SVD as a fully local "semantic-ish" signal — chosen specifically to avoid requiring an API key or a heavy model download at this stage. `hybrid.py` combines both rankings via reciprocal rank fusion. `chunking.py` projects each `Clause` into a `Chunk`, prepending the section title/term to the text used for indexing (`index_text`) while leaving the citable `text` field untouched — added after finding definitions whose own body never repeats the term they define. `stemming.py` is a hand-rolled Porter stemmer, added after finding exact-token matching missed obvious variants (`"periodically"` vs `"periodic"`, `"inspected"` vs `"inspection"`).

**Result:** recall@5 = 93.3% (14/15) on a golden question set built against verified real clause text, clearing the roadmap's ≥90% exit criterion — enforced as a test (`test_recall_at_5_meets_phase_2_exit_criteria`), not just claimed. One miss is documented as a known limitation (multiple other definitions legitimately cross-reference the target term, diluting lexical frequency) rather than chased into overfitting a 15-item set. 19 tests added (36 total).

**Files:** `src/safety_qa/retrieval/chunking.py`, `bm25.py`, `stemming.py`, `semantic.py`, `hybrid.py`, `retriever.py`, `eval_set.py`, `run_eval.py`, `ask.py`, `tests/test_retrieval.py`

---

## CHG-20260907-03 — Grounded generation with citation verification — 2026-09-07

**What:** Built Phase 3: the first component in the project that calls an LLM. Generates discrete, independently-checkable claims (never free prose) from retrieved clauses only, each with a citation and a verbatim quote, or an explicit unsupported flag.

**How it works:** `schema.py` defines the structured-claims contract (Pydantic). `llm_client.py` defines an `LLMClient` protocol with two implementations: `AnthropicClient` (real, forces structured output via tool-use) and `FakeLLMClient` (deterministic, records every call) — built this way specifically because no LLM API key was available at the time, so all logic had to be independently testable without one. `generator.py` orchestrates retrieve → prompt → structured call (schema-validated, retried once on failure) → a citation-grounding sanity check: every claim's cited clause must actually be among the retrieved chunks (catches hallucinated citations), and its quote must be an exact substring of that clause's text (catches paraphrasing disguised as quoting). Anything failing either check is dropped into `rejected_claims` with a reason, never silently trusted.

**Result:** 9 tests, all passing against `FakeLLMClient` — zero network calls, zero API key required. Documented explicitly as a deterministic floor underneath Phase 4's semantic grounding judge, not a replacement for it. (First real-API validation of this component happened later, in CHG-20260909-05.)

**Files:** `src/safety_qa/generation/schema.py`, `llm_client.py`, `prompt.py`, `generator.py`, `ask.py`, `tests/test_generation.py`

---

## CHG-20260907-04 — Judge 1: Grounding & Contradiction Judge — 2026-09-07

**What:** Built Phase 4: an independent LLM judge that re-checks every claim a generator produces, verdicting each `supported` / `contradicted` / `unsupported`.

**How it works:** Two layers. (1) A deterministic re-check, independent of Phase 3's own check — every claim's cited clause is re-fetched straight from the DB by a fresh `get_clause_by_path(standard_id, clause_path)` lookup (added to `store.py` for this — deliberately not reusing Phase 3's already-resolved chunk objects), and its quote re-verified verbatim from scratch. Failing this is `unsupported` with zero LLM calls spent. (2) Everything that clears step 1 goes into one **batched** LLM call per answer (cost-conscious, per the architecture doc's Sec 4.4 note), asking what string-matching can't: does the clause actually entail the claim, or does the claim misrepresent it (e.g. clause says "at least annually", claim says "monthly" — quote is verbatim-valid, claim is wrong).

**Result:** 10 tests passing against `FakeLLMClient`, covering the deterministic layer and all LLM-layer plumbing (batching into one call, claim_id-based response mapping, retry-once-then-fail). A 9-case adversarial eval set (`judging/eval_set.py`) was built for live validation, documented explicitly as needing a real model to prove (unlike Phase 2's recall@k, "does the judge catch a contradiction" has no dependency-free verification path). Real-model validation happened in CHG-20260909-05: 9/9 correct, 100% accuracy across all three verdict classes.

**Files:** `src/safety_qa/judging/schema.py`, `prompt.py`, `grounding_judge.py`, `eval_set.py`, `run_judge_eval.py`, `src/safety_qa/ingestion/store.py` (added `get_clause_by_path`), `tests/test_judging.py`

---

## CHG-20260909-05 — Kimi K3/K2.6 provider + first real-API validation of Phases 3-4 — 2026-09-09

**What:** Added Kimi (Moonshot AI) as a second LLM provider alongside Claude, wired up `.env`-based key management, and ran Phase 3 (generation) and Phase 4 (judging) against a live model for the first time in this project.

**How it works:** `KimiClient` implements the same `LLMClient` protocol as `AnthropicClient`, via Moonshot's OpenAI-compatible endpoint (`api.moonshot.ai/v1`) and OpenAI-style function-calling. Both real clients call `load_dotenv()` so a repo-root `.env` (gitignored) is picked up automatically — no code change needed to switch keys. `build_client(role, provider=None)` centralizes provider + model-tier selection (generator gets the highest-capability tier, judge gets the fast/cheap tier, per the arch doc's model-tiering design), defaulting to Kimi via `LLM_PROVIDER` since that's the provider actually configured with a real key. One API-shape issue found and fixed empirically (not clearly documented by Moonshot): Kimi's thinking-enabled models reject a pinned `tool_choice`, and `kimi-k2.6` additionally rejects `tool_choice="required"` — only `"auto"` works across models; the existing retry-on-missing-tool-call logic is the safety net for the rare case a call doesn't return one.

**Result:** Phase 3 generation, run for real: a real question produced 2 correctly grounded, cited claims, both passing verification. Phase 4's adversarial eval, run for real: 9/9 correct, 100% accuracy across all three verdict classes (supported/contradicted/unsupported) — including the hardest category, a verbatim-valid quote that still misrepresents the clause. 55 existing tests unaffected (all run against `FakeLLMClient`). Separately, `.gitignore` was extended to exclude `.history/` (a VS Code local-history extension found holding timestamped snapshots of `.env`) after discovering it during this change — confirmed via full git history search that neither it nor `.env` was ever committed.

**Files:** `src/safety_qa/generation/llm_client.py`, `ask.py`, `src/safety_qa/judging/run_judge_eval.py`, `pyproject.toml`, `.gitignore`, `.env.example`

---

## CHG-20260911-06 — Swap TF-IDF/LSA semantic leg for e5-base-v2 embeddings — 2026-09-11

**What:** Replaced the semantic leg of hybrid retrieval with real neural embeddings (`intfloat/e5-base-v2`, local via `sentence-transformers`), superseding the TF-IDF + truncated SVD approach from CHG-20260907-02.

**How it works:** `semantic.py` now encodes each chunk's `index_text` with e5-base-v2 (asymmetric convention: `"passage: "` prefix for indexed documents, `"query: "` prefix for queries, per the model card), L2-normalized at encode time so cosine similarity is a plain dot product. The loaded model is cached process-wide via `lru_cache`, not per `SemanticIndex` instance, so every `Retriever`/test in the same process shares one loaded model rather than each reloading a ~440MB model separately. `fit`/`score_all` kept the exact same interface, so `retriever.py` and `hybrid.py` needed zero changes. `scikit-learn` was dropped from dependencies (nothing else in the codebase used it).

**Why now, having chosen TF-IDF/LSA originally:** that earlier choice was driven by real embeddings appearing to need either an API key or a heavy local install (torch + transformers, ~1-2GB) — a trade-off the user explicitly declined to pay for a demo-stage decision at the time. That reasoning stopped holding once it was checked directly: torch (CUDA build) and transformers were already present in this environment, and a real GPU (RTX 5060 Laptop) was available — making the actual incremental cost just the `sentence-transformers` wrapper package, not the trade-off originally assumed.

**Result:** recall@5 = 100% (15/15), up from 93.3% (14/15). The one previously-documented known limitation (the "energy isolating device" definition losing to other definitions that cross-reference it, on pure lexical frequency) no longer reproduces — real embeddings resolve exactly the class of miss that was attributed to TF-IDF's lexical-frequency dependence. 55 tests passing (one updated: `test_semantic_index_scores_are_finite_and_bounded` dropped the now-nonexistent `n_components` parameter).

**Files:** `src/safety_qa/retrieval/semantic.py`, `pyproject.toml`, `tests/test_retrieval.py`, `README.md`
