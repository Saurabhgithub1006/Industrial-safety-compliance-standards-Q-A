# Audit Log

> Entries CHG-20260907-01 through CHG-20260909-05 are backfilled retrospectively on
> 2026-09-10 (see `artifacts/changelogs.md` for the same note). These are feature
> builds, not defect fixes, so "Root cause" is marked N/A where no defect was
> involved — filled in normally for the one entry (CHG-20260909-05) that did
> involve diagnosing a real failure (an API 400 error).

## CHG-20260907-01 — 2026-09-07

**Issue:** Begin Phase 1 of the roadmap (`artifacts/system-arch-and-roadmap.md`): clause-aware ingestion of a real safety-standard source into a queryable, citation-addressable store.

**Root cause:** N/A — feature build, not a defect fix. Core technical difficulty: the source eCFR XML encodes clause hierarchy as literal text markers in flat `<P>` tags, not as nested elements, and inline cross-references reuse the same bracket syntax as structural markers — ambiguous to resolve without a value-succession check (see below).

**Impact:** New capability, no prior functionality affected. 135 clauses of 29 CFR 1910.147 made independently queryable.

**Fix implemented:** Stack-based clause parser resolving each marker by literal value succession (a sibling is the next value in its class's sequence; a new nested list starts at its class's first value) rather than by punctuation or pattern class alone — the latter was tried first and found ambiguous (`i`/`c`/`d` are valid both as letters and as roman numerals; punctuation like trailing `:` vs `.` before a sub-list was not a reliable signal in the real document).

**Decisions made:**
- D1: Anchor the demo corpus on OSHA 1910.147 (public domain, clause-numbered) rather than the paywalled IEC/DIN text the project is ultimately about — recommended by agent, consistent with the corpus-scoping decision already recorded in `artifacts/system-arch-and-roadmap.md` Sec 1.
- D2: SQLite over Postgres for local storage — recommended by agent per the arch doc's "boring stack" choice; not contested.
- D3: Notes and the non-mandatory appendix are ingested but flagged `is_normative=False` rather than excluded — recommended by agent, reasoning recorded in `chunking.py`'s docstring (excluding them would make the system unable to answer legitimate questions about exceptions).

**Alternatives rejected:** Pure regex/punctuation-based marker-chain detection without value-succession checking — rejected after producing at least three concrete wrong-parse cases against the real document (documented as regression tests in `tests/test_ingestion.py`).

**Validation:** 17 tests, including 3 regression tests for the specific parsing bugs found and fixed; zero duplicate citation keys across 135 clauses; a spot-checked clause's text confirmed to match the real regulation.

**Follow-ups:** Only one standard (OSHA 1910.147) is ingested. IEC/ISO/DIN public front-matter, additional OSHA sections, and NFPA free-access text remain out of scope for now.

---

## CHG-20260907-02 — 2026-09-07

**Issue:** Phase 2 of the roadmap: retrieval over the Phase 1 corpus, meeting the roadmap's recall@5 ≥ 90% exit criterion.

**Root cause:** N/A — feature build, not a defect fix. Two real gaps were found and fixed during construction (see Decisions/Fix), discovered by running the initial implementation against the golden eval set rather than assumed upfront.

**Impact:** New capability. Initial implementation measured recall@5 = 73.3%, below the exit criterion.

**Fix implemented:** Added a hand-rolled Porter stemmer (`stemming.py`) after finding exact-token BM25/TF-IDF matching missed obvious morphological variants (query "periodically inspected" shared zero tokens with clause text "periodic inspection"); and changed chunk indexing to prepend the section title/term to the text used for search (`Chunk.index_text`) after finding definition entries whose body text never repeats the term they define (e.g. "Lockout device." → body never says "lockout device" again), while leaving the citable `Chunk.text` field unmodified.

**Decisions made:**
- D1: TF-IDF + truncated SVD (LSA) for the semantic leg instead of a neural embedding model — recommended by agent and confirmed by user (explicit exchange: user asked "does it need api for phase 2", agent recommended the local/no-API path, user confirmed "okay").
- D2: Reciprocal rank fusion to combine BM25 and semantic rankings, no learned reranker — per the arch doc's existing guidance, not re-litigated.
- D3: Stop chasing the one remaining recall miss (a definition diluted by other definitions cross-referencing it) rather than further tune against the 15-item eval set — recommended by agent specifically to avoid overfitting a small eval set; not contested.

**Alternatives rejected:** A real embedding API (Voyage AI) or a local sentence-transformers model — both considered in the initial provider discussion; rejected in favor of the zero-API/zero-heavy-install path per the user's confirmed preference.

**Validation:** recall@5 = 93.3% (14/15), verified via an automated test (`test_recall_at_5_meets_phase_2_exit_criteria`) that fails CI if it regresses below 0.9. 19 tests total for this change.

**Follow-ups:** The one remaining eval miss is documented as a known limitation (README, code comments), not resolved. A real embedding model or title-field boosting are the two paths noted as future options if retrieval quality needs to improve later.

---

## CHG-20260907-03 — 2026-09-07

**Issue:** Phase 3 of the roadmap: grounded generation — an LLM answering only from retrieved clauses, in structured, independently-checkable claims, with no LLM API key available at the time.

**Root cause:** N/A — feature build, not a defect fix.

**Impact:** New capability; first LLM-dependent component in the project. No API key was available, which directly shaped the design (see Decisions).

**Fix implemented:** An `LLMClient` protocol with `AnthropicClient` (real) and `FakeLLMClient` (deterministic, call-recording) implementations, so all generator logic — prompt construction, schema validation with one retry, and citation-grounding checks — is fully testable without a live model. `Generator.answer()` independently verifies every claim the model returns: cited clause must be among what was actually retrieved (catches hallucinated citations), and the quote must be an exact substring of that clause's text (catches paraphrasing disguised as quoting) — failing either drops the claim into `rejected_claims` with a reason rather than trusting it.

**Decisions made:**
- D1: Build against a fake LLM client rather than block the phase on obtaining an API key — recommended by agent given no key was available; user later confirmed this was acceptable ("so it means... also needed" exchange, user chose to defer key creation to later).
- D2: The citation-grounding check in this phase is explicitly documented as a deterministic floor, not a substitute for Phase 4's semantic judge — recommended by agent, not contested.

**Alternatives rejected:** None recorded — no live-API alternative was available to weigh at the time.

**Validation:** 9 tests, all against `FakeLLMClient`, covering valid claims, hallucinated-citation rejection, non-verbatim-quote rejection, whitespace-tolerant verbatim matching, unsupported-aspects passthrough, and retry/failure behavior. Real-model validation deferred to, and completed in, CHG-20260909-05.

**Follow-ups:** None at the time of this change; superseded by real-API validation in CHG-20260909-05.

---

## CHG-20260907-04 — 2026-09-07

**Issue:** Phase 4 of the roadmap: an independent judge that re-checks every claim Phase 3 produces, verdicting supported/contradicted/unsupported, without trusting Phase 3's own framing.

**Root cause:** N/A — feature build, not a defect fix.

**Impact:** New capability. No prior functionality affected.

**Fix implemented:** Added `get_clause_by_path(standard_id, clause_path)` to `ingestion/store.py` specifically so Judge 1 resolves each claim's cited clause via its own fresh DB lookup, never reusing Phase 3's already-resolved chunk objects — the literal mechanism behind "must not just trust the generator's framing." `GroundingJudge.evaluate_claims()` re-verifies citation existence and verbatim quoting from scratch (zero LLM calls if either fails), then batches everything that passes into one LLM call per answer (cost design, not one call per claim) asking the semantic question deterministic checking can't: does the quote actually entail the claim.

**Decisions made:**
- D1: Batch all of an answer's claims into one LLM call rather than one call per claim — recommended by agent in the earlier architect-review pass on `system-arch-and-roadmap.md`, carried through into implementation.
- D2: Judge 1 independently re-fetches clause text rather than trusting the `Claim` object's own citation fields — recommended by agent as the correct reading of the arch doc's "must not just trust the generator's framing" requirement; not contested.
- D3: The adversarial eval set (`judging/eval_set.py`) is explicitly documented as needing a live model to validate, and is not CI-enforced the way Phase 2's recall@k is — recommended by agent, reasoning: no dependency-free way exists to verify semantic judgment quality.

**Alternatives rejected:** Reusing Phase 3's chunk-resolution result directly in Judge 1 (simpler, less code) — rejected as contrary to the independence requirement the whole phase exists to satisfy.

**Validation:** 10 tests against `FakeLLMClient`, covering the deterministic layer and LLM-layer plumbing (batching, claim_id mapping, retry-then-fail). Real-model validation deferred to, and completed in, CHG-20260909-05: 9/9 correct, 100% accuracy.

**Follow-ups:** None at the time of this change; superseded by real-API validation in CHG-20260909-05.

---

## CHG-20260909-05 — 2026-09-09

**Issue:** User requested using Kimi K3 (Moonshot AI) instead of a fake/placeholder client for Phases 3-4, having obtained a Kimi API key rather than an Anthropic one.

**Root cause:** A real defect surfaced during this change: `KimiClient.complete_structured()` initially used a pinned `tool_choice` (`{"type": "function", "function": {"name": schema_name}}`, mirroring `AnthropicClient`'s pattern). Live calls to `kimi-k3` failed with `openai.BadRequestError: 400 - tool_choice 'specified' is incompatible with thinking enabled`; switching to `tool_choice="required"` fixed `kimi-k3` but then `kimi-k2.6` failed with the same category of error (`tool_choice 'required' is incompatible with thinking enabled`) when used as the judge model.

**Impact:** Both Phase 3 (`generation.ask`) and Phase 4 (`judging.run_judge_eval`) were non-functional against the live Kimi API until fixed — first real-API run of either phase, so no prior working state was broken by this, but the initial implementation could not complete a real call at all.

**Fix implemented:** `tool_choice="auto"` — verified empirically (Moonshot's docs did not clearly state this constraint) to work across both `kimi-k3` and `kimi-k2.6` via three direct API calls (`type='function'` pinned form → 400 on k3; `"required"` → succeeded on k3, 400 on k2.6; `"auto"` → succeeded on k2.6). Since exactly one tool is ever offered per call, `"auto"` reliably triggers the tool call in practice; existing retry-on-missing-tool-call logic in `generator.py`/`grounding_judge.py` remains the safety net for the rare case it doesn't.

**Decisions made:**
- D1: Add Kimi as an alternative provider (keeping `AnthropicClient`) rather than replacing Claude entirely — user selected this explicitly after being presented both options.
- D2: `build_client()` defaults to Kimi via `LLM_PROVIDER`, since that's the provider actually configured with a real key — recommended by agent, not contested.
- D3: `.env`-based key management, loaded via `load_dotenv()` in both real clients — user requested this approach specifically ("api by creating .env in root directory").

**Alternatives rejected:** None recorded for the tool_choice fix — the three tested values were the complete set of plausible options (pinned / required / auto) and "auto" was the only one that worked across both models used.

**Validation:** Phase 3 real run: 1 question → 2 correctly grounded, cited claims. Phase 4 real run: 9/9 adversarial cases correct, 100% accuracy across all three verdict classes. 55 pre-existing tests re-run and confirmed unaffected (all use `FakeLLMClient`).

**Follow-ups:** Kimi account is rate-limited to 3 requests/minute on the current tier — noted as an operational constraint for future real-API runs, not addressed further. The Kimi key's value was incidentally exposed to the assistant's session context via an IDE file-diff notification when the user edited `.env` directly (never committed, never requested) — user was advised rotation is a reasonable precaution if being maximally cautious; not required, no action taken.

---

## CHG-20260911-06 — 2026-09-11

**Issue:** User asked why hybrid retrieval used TF-IDF instead of a real embedding model (naming e5-base-v2 / jina specifically), after the semantic-leg design was explained. Not a bug report — a design question that surfaced a decision worth revisiting.

**Root cause:** N/A in the defect sense — this is a design-tradeoff change, not a fix. The original TF-IDF/LSA choice (CHG-20260907-02) was based on an assumption (real embeddings = heavy install or API cost) that was checked directly during this change and found no longer accurate for this environment: `torch` (CUDA build) and `transformers` were already installed, and a GPU (RTX 5060 Laptop) was available — verified via direct `import torch; torch.cuda.is_available()` check before proposing the change, not assumed.

**Impact:** Retrieval quality measurably improved: recall@5 went from 93.3% to 100% on the golden eval set. No regression — all 55 tests still pass (one updated for the new constructor signature).

**Fix implemented:** Replaced `semantic.py`'s TF-IDF + truncated SVD internals with `intfloat/e5-base-v2` sentence embeddings via `sentence-transformers`, keeping the exact same `fit`/`score_all` interface so no other file needed to change. Model loading cached process-wide via `lru_cache` rather than per-instance, to avoid reloading a ~440MB model repeatedly (verified: full test suite completed in ~15s, one model load for the whole run).

**Decisions made:**
- D1: Proceed with the e5-base-v2 swap now, before Phase 5, rather than after — recommended by agent ("so Phase 5's HITL review is working with the better-quality retrieval"), confirmed by user ("start then").
- D2: e5-base-v2 over jina-embeddings as the specific model — recommended by agent (simpler asymmetric-prefix convention, well-benchmarked, context length not a binding constraint at this corpus's scale); user did not specify a preference, agent's recommendation was taken by proceeding.
- D3: Drop `scikit-learn` from dependencies as part of the same change, since nothing else in the codebase used it — treated as a direct, minimal-diff consequence of the approved plan rather than a separate decision point.

**Alternatives rejected:** jina-embeddings-v2/v3 — not rejected outright, offered as an explicit alternative; e5-base-v2 was recommended and the user proceeded without countering it.

**Validation:** `run_eval.py` re-run for real: recall@5 = 100% (15/15), up from 93.3%. Full test suite re-run: 55/55 passing. Manual sanity check before the full eval: a 3-document toy corpus correctly ranked the semantically matching document highest (0.898) over two unrelated ones (0.665, 0.717).

**Follow-ups:** First run of `semantic.py` on a machine without the model cached will download ~440MB from Hugging Face — not an issue in this environment (already cached now) but worth knowing if this repo is cloned fresh elsewhere. `artifacts/system-arch-and-roadmap.md`'s tech-stack section already described "dense embeddings" generically and did not need updating; only `README.md`'s Phase 2 status section referenced TF-IDF/LSA specifically and was updated.

---

## CHG-20260911-07 — 2026-09-11

**Issue:** Begin Phase 5 of the roadmap: Judge 2 (escalation packaging of Judge 1's flagged claims) and HITL review (human approve/edit/reject), wired into answer assembly so only `supported` claims and human-cleared ones reach a final answer.

**Root cause:** N/A — feature build, not a defect fix.

**Impact:** New capability. No prior functionality affected — `review/` only reads `JudgedAnswer` objects Phase 4 already produces.

**Fix implemented:** `review/escalation.py` (severity-ranked packet construction, zero LLM calls), `review/store.py` (persistent queue in its own DB file, dedup-on-insert against pending items only), `review/cli.py` (interactive reviewer loop with decision logic split out for testability), `review/assembly.py` (final answer = `supported` + HITL-cleared claims, pending/rejected held back and counted), `review/pipeline.py` (end-to-end wiring).

**Decisions made:**
- D1: Judge 2 makes zero LLM calls (severity ranking and deduping are mechanical) — presented as a decision point with an LLM-summary alternative noted as a deferrable enhancement; user chose Option A.
- D2: HITL review interface is a CLI, consistent with the project's existing `ask.py`/`run_eval.py` pattern, rather than a new web-UI (e.g. Streamlit) dependency — presented as a decision point; user chose Option A.
- D3: The review queue lives in a database file separate from `corpus.db` — recommended by agent (queue data is real human-decision history that must never share a file with something `run_ingest` can rebuild), not escalated as a full decision point since there was a clear best-practice answer and low controversy; stated in the plan, not contested.
- D4: An edited claim is not re-run through Judge 1's automated grounding check — the human review is treated as the final check for that claim — recommended by agent, not contested.
- D5: Dedup-on-insert only merges against a still-*pending* item, not an already-decided one — recommended by agent (a claim recurring after being rejected/approved is a new instance worth a human seeing again, not noise to suppress), not contested; added as its own test (`test_enqueue_does_not_dedup_against_already_decided_items`) after being identified as a real edge case during implementation, not caught in the original plan.

**Alternatives rejected:** An LLM-written summary per escalation packet (D1, Option B) — not rejected outright, offered as a later, additive enhancement. A Streamlit review UI (D2, Option B) — same treatment, deferred rather than rejected.

**Validation:** 16 new tests (71 total), all passing, zero LLM dependency for this phase. Live end-to-end smoke test: a real Kimi Judge 1 call correctly verdicted a deliberately wrong claim ("monthly" vs. the clause's actual "at least annually") as `contradicted`; Judge 2 built the escalation packet against the real corpus; the claim was correctly excluded from the final answer both before review (`pending_count=1`) and after a simulated reject decision (`rejected_count=1`), using a throwaway queue database, not the real one.

**Follow-ups:** No automated test exercises the interactive `input()`-driven loop in `cli.py` itself (only its underlying `apply_decision` function) — acceptable given the project's existing convention (other CLIs like `generation/ask.py` aren't loop-tested either), but worth knowing if the CLI's prompt-handling logic grows more complex later. Phase 6 (feedback/regression harness) is expected to consume `review_decision` rows as its labeled dataset — not built yet.

---

## CHG-20260911-08 — 2026-09-11

**Issue:** Begin Phase 6 of the roadmap: turn Phase 5's `review_decision` history into a regression suite and a judge-precision metric. Real review history was needed to build against (D1 from the Phase 6 kickoff, Option A) but the real queue was empty.

**Root cause:** A real defect surfaced during this change, not assumed upfront: the first version of `run_regression.py`'s replay logic treated every overturned case identically, replaying it through a live Judge 1 call and labeling a still-flagged result `REGRESSION`. Running it against real seeded data (see Impact) showed this mislabels a case that was originally caught by the deterministic verbatim-quote check, not Judge 1's own LLM judgment -- that check is a pure string/lookup comparison that will reproduce the identical result on every replay unless the underlying corpus text changes, so "replaying" it establishes nothing about drift and the `REGRESSION` label actively misrepresents what happened.

**Impact:** Before the fix, a genuinely fine transcription-error correction (see below) would have been reported as a "regression" on every future run of `run_regression.py`, permanently and misleadingly, until the item was resolved out of the queue -- a false-alarm risk for whoever reads that report. Caught here, before merge, rather than after.

**Fix implemented:** Added `judge1_source` ("deterministic_check" or "llm_judge") to `EscalationPacket` and the `review_item` table (with a migration, since the real `review_queue.db` file already existed under the old schema from CHG-20260911-07's seeding and `CREATE TABLE IF NOT EXISTS` doesn't retroactively add columns to it). `run_regression.py` now only replays `llm_judge`-sourced cases through the model; deterministic-sourced ones are listed separately with an explicit note that they were not replayed and why.

**Decisions made:**
- D1 (carried from Phase 0 intake): build the harness against real review history rather than pure fixtures — user chose Option A.
- D2: when 3 organic real questions produced zero escalations, deliberately inject known-wrong claims through the real pipeline (same transparent technique as CHG-20260911-07) rather than keep trying organic questions indefinitely or fabricate review_decision rows directly — recommended by agent, consistent with the precedent already set and disclosed in CHG-20260911-07; not contested (no live turn-taking needed, proceeding was implicit in the approved plan).
- D3: use a schema migration (`ALTER TABLE ADD COLUMN`) rather than deleting and recreating the already-existing `review_queue.db` file — recommended by agent specifically to avoid a destructive action on an existing database file without asking, even though the file only held the agent's own just-created seed data; not contested.
- D4: the one row whose `judge1_source` the migration's default value got wrong (seed3, defaulted to `llm_judge` but was actually `deterministic_check`) was corrected via a direct `UPDATE` rather than left inaccurate, since the true value was known from the earlier live call's actual output — agent action, not escalated as it was a direct factual correction, not a judgment call.

**Alternatives rejected:** Skipping the real-data seeding and building purely against synthetic fixtures (Option B from the Phase 0 intake) — not chosen; Option A was.

**Validation:** 6 new tests (77 total) covering `overturned_cases()`/`override_rate()` against synthetic data, all passing. Live validation against the real, corrected queue: `run_regression.py` reports override rate 33.3% (1/3), correctly identifies the one overturned case as deterministic-sourced, explicitly declines to replay it, and reports "no LLM-judged overturned cases to replay" (accurate — neither genuine rejection was overturned).

**Follow-ups:** No genuine `llm_judge`-sourced overturned case exists yet in the real queue (both live LLM-caught flags were confirmed correct via reject, not overturned) -- the replay-and-detect-regression code path is validated by the pure unit tests and by direct reasoning about its logic, but has not yet been exercised end-to-end against a real case that should show `ok` after a genuine judge misfire. This will happen naturally once real usage produces one.
