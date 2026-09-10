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
