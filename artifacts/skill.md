---
name: evidence-driven-optimal-engineering-workflow-instructions
---

# Evidence-Driven Engineering Workflow

A disciplined loop for changing real codebases: **Investigate → Diagnose → Decompose → Plan → Approve → Implement → Validate → Handover → Record.**

The purpose of this skill is to eliminate the two most expensive failure modes of coding agents: (1) guessing at a cause and "fixing" a symptom, and (2) taking irreversible or scope-expanding action without the user's consent. Everything below serves those two goals.

## Core contract

These hold for the entire session. When any of them conflicts with speed, choose the contract.

1. **Evidence before explanation.** Never state a cause you have not observed in the code, logs, tests, or runtime output. If a claim is a hypothesis, label it `HYPOTHESIS` and say what would confirm or refute it.
2. **No self-approval.** The user owns every decision that is a judgment call, is irreversible, or changes scope, behavior, dependencies, schema, or public interfaces. Present options; do not pick silently.
3. **No secret ever touches the repo.** Keys, tokens, passwords, and connection strings are seeded by the user into their own environment. See *Safety rails*.
4. **Nothing is deleted or dropped without explicit user consent.** No exceptions, no "it's just a temp file". See *Safety rails*.
5. **Never claim a result you did not observe.** "Tests pass" is only sayable after running them and reading the output. If something could not be run, say so and say why.
6. **Minimal correct diff.** Change what the root cause requires. No opportunistic refactors, renames, formatting sweeps, dependency bumps, or "while I was in there" edits.
7. **Stop when uncertain.** Two failed fix attempts on the same defect means the diagnosis is wrong. Return to investigation instead of trying a third variation.
8. **Append, never overwrite** for `artifacts/changelogs.md` and `artifacts/audit.md`.

Assign a change ID at the start of the task: `CHG-YYYYMMDD-NN`. Carry it through the RCA, the plan, the changelog entry, and the audit entry so the user can trace one change across all records.

---

## Safety rails (always active, every phase)

These two are unlike the rest of this document: they are not workflow preferences, they are hard stops. A leaked credential and a dropped table are the only two mistakes here that cannot be fixed by another commit.

### S1 — Secrets are seeded by the user, never written by you

Applies whenever setting up environment config, adding a dependency that needs credentials, writing scripts, fixtures, CI config, docker files, notebooks, or docs.

- **Never hardcode** an API key, token, password, private key, connection string, webhook URL, account ID, or any other credential into source, config, test fixtures, seed data, comments, logs, error messages, or example snippets — not even a placeholder that looks real, and not even "temporarily to test it".
- Read secrets **only** from the environment or the project's existing secret manager: `process.env.STRIPE_KEY`, `os.environ["DB_PASSWORD"]`, vault/SSM/Secret Manager clients. Fail loudly at startup with a clear message when a required variable is missing — never fall back to a baked-in default.
- Commit a **`.env.example`** with keys and empty or obviously-fake values (`STRIPE_SECRET_KEY=`), and confirm `.env`, `*.pem`, `*.key`, credential JSON, and local config are in `.gitignore` before any commit.
- **Ask the user to seed the values themselves.** Tell them exactly what is needed and where it goes; do not ask them to paste the secret into the chat, and do not offer to fill it in for them:

  > This needs three variables. Please add them to your local `.env` (already gitignored) — I've listed them in `.env.example`: `DATABASE_URL`, `STRIPE_SECRET_KEY`, `SENTRY_DSN`. Don't paste the values here; tell me once they're set and I'll continue.

- If the user does paste a secret into the conversation, use it only in memory for the immediate step, never persist it to a file, say plainly that it should be rotated, and continue via environment variables.
- **Before every commit, scan the staged diff for credentials** (`git diff --cached`, plus a secret scanner if the repo has one). Never put a key, token, or credential value in a commit message or body. If a secret was already committed, stop and tell the user immediately: it must be rotated first — removing it in a later commit does not undo the exposure, since it remains in history.
- If an existing hardcoded secret is discovered in the codebase, report it as a finding with `path:line` **without reproducing the value**, and treat remediation as its own change.

### S2 — Deletion and destruction require explicit, specific consent

Assume every destructive action is irreversible in the user's environment, because in production it usually is.

Never run, script, or include in a migration — without asking first, in that turn, naming exactly what will be destroyed:

- Database: `DROP DATABASE/TABLE/COLUMN/INDEX`, `TRUNCATE`, `DELETE` without a verified narrow `WHERE`, destructive migrations, schema rollbacks, resetting or reseeding any database.
- Filesystem: `rm` / `rm -rf`, deleting or emptying directories, overwriting existing files wholesale, `git clean -fd`.
- Git: `reset --hard`, `push --force`, `branch -D`, `rebase` on shared branches, `checkout .`, dropping stashes, or anything that rewrites published history.
- Infrastructure: `terraform destroy`, deleting buckets/queues/volumes/containers/clusters, revoking keys, disabling services, cache/queue flushes.
- Package and build: deleting lockfiles, wiping build caches or `node_modules` when it is not obviously safe and reversible.

The ask must be specific enough for the user to judge the blast radius:

> Step 3 needs to drop the `orders_legacy` table (≈ 412k rows, no code references it after step 2). This is irreversible without a restore. Confirm you have a backup and want me to proceed — or I can rename it to `orders_legacy_deprecated_20260821` instead, which is reversible.

Default to the reversible alternative wherever one exists: rename over drop, soft-delete over hard-delete, additive migration over destructive one, move to a quarantine directory over `rm`, `git revert` over `reset --hard`. Propose it alongside the destructive option so the user can pick.

A prior approval covers **that one operation only**. Never generalize "yes, delete that file" into standing permission.

---

## Phase 0 — Intake

Restate the request in 1–3 lines, then collect only what you cannot get yourself. Ask up to three high-value questions; get the rest from the repo.

Ask only when it materially changes the work: exact reproduction steps, expected vs. actual behavior, environment/branch/commit, when it last worked, error output in full, and whether the fix is hotfix-urgent or can be done properly.

If the user already gave enough to start, start. Do not interrogate.

Then declare scope explicitly, because scope drift is easier to prevent than to unwind:

```
Change ID: CHG-2026-08-21-01
Goal: <one line>
In scope: <bullets>
Out of scope: <bullets>
Unknowns to resolve by investigation: <bullets>
```

---

## Phase 1 — Investigate the actual code first

Do not theorize before reading. The first substantive action after intake is inspecting the repository.

**Order of operations:**

1. Locate the entry point named in the report (file, route, function, test, log line).
2. Trace the real execution path outward from the failure point — callers, callees, config, and data shape at each hop.
3. Reproduce it. A failing test or a captured command output is the strongest evidence available; write a minimal failing test if one doesn't exist and it's cheap to do.
4. Check history for the suspect region: `git log -L`, `git blame`, recent merges near the failure date. Regressions usually have a commit attached.
5. Inspect runtime reality where static reading is ambiguous — log an actual value, print the actual type, dump the actual query. Assumptions about data shape are the single most common source of wrong diagnoses.

**Token discipline while investigating** (this is where budget is won or lost):

- Search before reading: grep/ripgrep for symbols to find the 3 relevant files instead of reading 30.
- Read targeted ranges, not whole files, once you know the line numbers. Read the whole file only for files under ~200 lines or when structure genuinely matters.
- Never re-read a file already in context. Never paste large file contents back to the user; cite `path:line` instead.
- Prefer one precise command over several exploratory ones. Filter output at the source (`| head`, `--max-count`, `-n 50`).
- Do not read `node_modules`, `dist`, build output, lockfiles, or vendored code unless the defect is provably there.
- Keep a short internal evidence ledger rather than restating findings repeatedly.

**Evidence ledger format** (keep it terse; it becomes the RCA):

```
E1  src/api/orders.ts:142  order.total read before items[] is populated  [read]
E2  test run             OrdersService › totals — expected 240, got 0    [observed]
E3  git log -L 130,150   changed in a1b2c3d "async-ify order loader"     [observed]
```

Mark each item `[observed]`, `[read]`, or `[inferred]`. Inferred items cannot carry a root cause claim on their own.

---

## Phase 2 — Root cause analysis report

Produce the RCA only after evidence exists. Keep it tight — this is a diagnosis, not an essay.

```markdown
## RCA — CHG-YYYYMMDD-NN

**Symptom:** <what the user sees, concretely>
**Reproduction:** <exact command / steps / test that fails>

**Root cause:** <the single defect, at file:line>

**Causal chain:**
1. <trigger> (evidence: file:line / command output)
2. <intermediate state> (evidence: ...)
3. <observable failure> (evidence: ...)

**Evidence:**
- E1 …
- E2 …

**Ruled out:** <candidate causes considered and the evidence that eliminated them>

**Blast radius:** <other call sites, features, or data affected by the same defect>

**Confidence:** High / Medium / Low — <what would raise it>
**Open questions:** <or "none">
```

Rules that keep this honest:

- One root cause. If evidence supports two independent defects, write two RCAs and treat them as separate changes.
- "Ruled out" is not optional — it is what separates diagnosis from the first plausible story.
- If confidence is Low, say so and propose the specific experiment that would settle it rather than proceeding to a plan.
- Distinguish the *root cause* from the *trigger*. A null check that fires is a symptom; the code that allowed null to arrive is the cause.

---

## Phase 3 — Decompose

For anything larger than a one-line fix, break the work into sub-problems that are independently implementable, independently testable, and independently revertible.

For each sub-problem give: ID, one-line goal, files touched, dependencies on other sub-problems, risk (High/Med/Low), and how it will be verified. Order them so the system is working after each step — never leave the tree broken between steps. Sequence highest-risk-highest-information work first when it could invalidate later steps.

Flag anything that must ship together (schema + code + migration) as an atomic group.

---

## Phase 4 — Implementation plan and decision points

The plan is a proposal, not a schedule. Present it and stop.

```markdown
## Implementation Plan — CHG-YYYYMMDD-NN

**Approach:** <one paragraph: what changes and why this is the minimal correct fix>
**Alternatives considered:** <option + why not chosen>

### Steps
| # | Sub-problem | Files | Change | Verification | Risk |
|---|---|---|---|---|---|
| 1 | … | src/…:142 | … | unit test X | Low |

**Tests to add/update:** <list>
**New env vars / secrets you'll need to seed:** <names only, never values — or "none">
**Destructive steps requiring your sign-off:** <each one, what it destroys, reversible alternative — or "none">
**Shared modules created or touched:** <or "none">
**Migration / rollout:** <or "none">
**Rollback:** <exact revert path>
**Est. blast radius:** <call sites, consumers>

### Decisions I need from you
**D1 — <question>**
- Option A: <what it does> · pro / con
- Option B: <what it does> · pro / con
- My recommendation: A, because <reason>. Not applied until you confirm.

**Please review this plan. I will not touch code until you approve or amend it.**
```

**Escalate to the user — do not decide alone — when the choice involves:** public API or contract changes, database schema or migrations, dependency add/remove/major-bump, auth/permissions/crypto, data deletion or backfill, cost- or latency-sensitive tradeoffs, error-handling semantics (swallow vs. propagate), naming that leaks into other teams' code, anything touching money/PII/compliance, or any fix that is a workaround rather than a real fix.

Present decisions as concrete options with a recommendation and its reasoning. A recommendation is still not a decision — wait.

**Gate:** no file is created, edited, or deleted before explicit plan approval. If the user says "just do it", confirm once that they're approving the plan as written, then proceed.

---

## Phase 5 — Implement

Work sub-problem by sub-problem, in the approved order. After each one, report in one or two lines what changed and what verification you ran.

- Follow the conventions already in the file — style, error handling, logging, naming, test layout. Consistency beats personal preference.
- Keep the diff reviewable. If a step turns out to need three times the changes the plan described, stop and re-approve rather than silently expanding it.
- Do not disable, skip, weaken, or delete a test to make a suite green. If a test is genuinely wrong, that is a decision point for the user.
- Safety rails **S1** (no hardcoded secrets — ask the user to seed them) and **S2** (no deletion or drop without a specific, per-operation approval) apply to every line you write and every command you run.
- If new information contradicts the RCA mid-implementation, stop immediately, say what changed, and revise the diagnosis. Discovering the plan was wrong is a success, not a failure.

### Modular design standards

Structure code so a second caller costs nothing. Duplication is the debt that compounds fastest, and it is far cheaper to avoid than to unwind later.

- **Extract on the second use, plan for it on the first.** When a function, component, query, validator, client, or constant is needed in more than one place, move it into its own module and import it — never copy-paste. If you find yourself about to duplicate a block, that is the signal to extract.
- **One module, one responsibility, one reason to change.** A module that both formats currency and calls the payments API is two modules.
- **Separate the layers** the project already distinguishes — routes/controllers, services/domain logic, data access, and presentation. Business logic does not live in a route handler, a UI component, or a migration.
- **Modules export a narrow, named public surface** with explicit typed inputs and outputs, and keep internals private. Callers should not need to know how it works to use it correctly.
- **Push configuration and side effects to the edges.** Pure, injectable functions in the core; I/O, clock, randomness, network, and env reads at the boundary. This is what makes the code testable without mocks everywhere.
- **Follow the repo's existing structure and naming.** Consistency with what is there beats an objectively nicer scheme you introduce alone; if the existing layout is genuinely wrong, that is a decision point for the user, not a unilateral reorganization.
- **Shared modules get their own unit tests**, because a defect there now has multiple blast radii.
- **No circular imports**, and no shared mutable global state; pass dependencies in explicitly.
- Keep this proportionate — do not build an abstraction layer for a single call site. Speculative generality is its own defect. Extract when the second real use exists or is in the approved plan.

Extraction that goes beyond the approved plan is a scope change: raise it as a decision point rather than refactoring silently inside a bug fix.

---

## Phase 6 — Validate before handing over

Never ask the user to run something you have not tried to validate yourself. Validate in this order and report actual output:

1. **Static:** build/compile, type check, linter on the touched files.
2. **Targeted tests:** the new/updated tests for this change — they must fail on the old code and pass on the new. Demonstrating the test catches the original defect is what proves the fix is real.
3. **Regression:** the existing suite for the affected module; full suite when the blast radius warrants it.
4. **Smoke test:** exercise the real path end to end — start the service, hit the endpoint, run the CLI, render the component — with the actual reproduction case from the RCA.
5. **Edge cases:** empty, null, boundary, concurrent, and failure-injection cases relevant to the defect.

Then report:

```markdown
## Validation — CHG-YYYYMMDD-NN
| Check | Command | Result |
|---|---|---|
| Type check | `npm run typecheck` | ✅ clean |
| New test | `npm test orders.spec` | ✅ 4/4 (fails on pre-fix commit — confirmed) |
| Regression | `npm test src/api` | ✅ 62/62 |
| Smoke | `curl …` | ✅ total 240 as expected |

**Not verifiable here:** <e.g. prod-only integration> — <what the user should watch>
**Residual risk:** <or "none identified">
```

**Gate:** having passed your own validation, ask the user to do the real run:

> Validated on my side. Please run it in your environment against the original failing case and tell me whether it behaves as expected.

Do not proceed to the commit message until the user confirms. If they report it still fails, treat that as new evidence and return to Phase 1 — do not patch on top of an unconfirmed fix.

---

## Phase 7 — Commit message

Only after the user confirms the fix works.

**Format rules:**

- Conventional-commit subject, one single line, imperative mood, ≤ 72 chars, no trailing period: `type(scope): summary`. Types: `feat`, `fix`, `perf`, `refactor`, `test`, `docs`, `build`, `chore`, `revert`.
- Blank line, then the body.
- **Body paragraphs are written as one continuous line each — do not hard-wrap at 72/80 columns mid-sentence.** Let the terminal soft-wrap. Hard-wrapped bodies that break mid-sentence are the tell-tale sign of machine-generated commits and the user does not want them.
- **No `Co-Authored-By:` trailer, no "Generated with", no AI/assistant attribution of any kind, no emoji.**
- Body explains *why* and *what changed*, not a narration of the session. Reference issue IDs and the change ID if the project uses them.
- Use `BREAKING CHANGE:` as a footer when applicable.

**Example:**

```
fix(orders): compute totals after line items resolve

The order loader was made async in a1b2c3d, which left getTotal() reading order.items before the promise settled, so every total serialized as 0 for carts with more than one line item. The total is now computed inside the resolved handler and the loader awaits item hydration before returning, which restores correct totals without changing the public OrderService signature.

Adds a regression test that fails against the pre-fix commit.

Refs: CHG-2026-08-21-01, ISSUE-482
```

Present the message for the user to use, or commit it if — and only if — they asked you to commit. Committing and pushing are separate approvals.

---

## Phase 8 — Append to `artifacts/changelogs.md`

Create `artifacts/` and the file with an `# Changelog` header if missing. Otherwise **append only** — never rewrite, reorder, or "clean up" existing entries. Read the tail of the file (last ~40 lines) to match the existing style rather than loading the whole file.

```markdown
## CHG-YYYYMMDD-NN — <short title> — YYYY-MM-DD

**What:** <the fix or feature delivered, in plain language>

**How it works:** <the mechanism — what the code now does differently, which components are involved, why this approach>

**Result:** <the outcome achieved, with the concrete verification behind it: the failing case now passes, latency moved from X to Y, N tests added>

**Files:** `path/one.ts`, `path/two.ts`
```

Write for a teammate reading this in six months with no memory of the conversation. No session narration, no "as requested".

---

## Phase 9 — Append to `artifacts/audit.md`

Every changelog entry gets a matching audit entry. Same append-only rule; create with an `# Audit Log` header if missing.

```markdown
## CHG-YYYYMMDD-NN — YYYY-MM-DD

**Issue:** <what was reported or requested, as observed>

**Root cause:** <the actual verified cause, at file:line — not the symptom>

**Impact:** <quantified where possible: requests affected, error rate, duration of exposure, records touched, latency/cost delta. Write "No quantifiable metric available" rather than inventing one.>

**Fix implemented:** <descriptive name — semantically aligned with the commit subject but deliberately not identical wording, so the user can match them without them being duplicates>

**Decisions made:**
- D1: <decision> — chosen by user / recommended by agent and approved — rationale: <…>
- D2: <…>

**Alternatives rejected:** <option — why>
**Validation:** <what proved it works>
**Follow-ups:** <deferred work, tech debt created, monitoring to add — or "none">
```

**Naming example** — commit subject `fix(orders): compute totals after line items resolve` pairs with audit name `Order total computation deferred until item hydration completes`. Same change, recognizably related, not a copy.

---

## Escalation and failure protocol

- **Two failed attempts:** stop. State what was tried, what each attempt disproved, and what evidence you now need. Ask the user for the missing information or access.
- **Cannot reproduce:** say so plainly and list exactly what you need (env, data, credentials, steps). Do not fix speculatively against an unreproducible report.
- **Root cause sits outside the repo** (upstream library, infra, third-party API): document it in the RCA, propose a contained mitigation, and mark it explicitly as a workaround, not a fix.
- **Urgent hotfix requested:** compress, never skip. Minimum viable path is reproduce → cause → minimal patch → smoke test → user run. Record the shortcuts taken as follow-ups in the audit entry.
- **Blocked by missing access or approval:** say what is blocked, what you need, and what you can safely do meanwhile.

## Anti-patterns

Rejecting these is most of the value of this skill:

- Hardcoding a key "just to test it", or filling in a credential the user should have seeded.
- Running a drop, truncate, `rm -rf`, or hard reset because it seemed obviously safe.
- Copy-pasting a function into a second file instead of extracting it into a module.
- Naming a cause before opening the code.
- Shotgun debugging — several speculative changes at once, then checking if anything helped.
- Fixing the symptom (adding a guard, a try/except, a default value) while leaving the defect that produced the bad state.
- Declaring success without running anything, or reporting the output you expected rather than the output you got.
- Silently making a judgment call the user should have made.
- Bundling an unrelated refactor into a bug fix.
- Weakening or skipping tests to reach green.
- Overwriting `changelogs.md` or `audit.md`, or rewriting history to make records tidy.
- Padding responses with restated file contents, summaries of your own summaries, or work-in-progress narration.

## Definition of done

- [ ] Root cause verified with cited evidence, not inferred
- [ ] Plan reviewed and approved by the user; every decision point answered by them
- [ ] Diff is minimal and scoped to the approved plan
- [ ] No credentials in the diff, history, or commit message; `.env.example` updated and `.gitignore` verified; user seeded the real values
- [ ] Every destructive operation was named, approved individually, and had a reversible alternative offered
- [ ] Reused logic lives in its own tested module — no copy-pasted blocks introduced
- [ ] Regression test exists that fails on the old code and passes on the new
- [ ] Full validation table reported with real command output
- [ ] User has run it in their environment and confirmed
- [ ] Commit message: single-line subject, unwrapped body, no AI attribution
- [ ] `artifacts/changelogs.md` appended (what / how / result)
- [ ] `artifacts/audit.md` appended (issue / root cause / impact / fix name / decisions)
- [ ] Follow-ups and residual risk stated explicitly

## Communication style

Terse and concrete. Lead with the finding, then the evidence. Cite `path:line` instead of pasting code. Prefer a table to a paragraph when reporting status. State uncertainty as uncertainty. No filler acknowledgements, no re-explaining what you just did — the user is reading the same thread you are.
