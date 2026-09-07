# Raw corpus sources

| File | Standard | Source | License | Retrieved |
|---|---|---|---|---|
| `osha_1910_147_raw.xml` | 29 CFR 1910.147 — The control of hazardous energy (lockout/tagout) | [eCFR](https://www.ecfr.gov/current/title-29/subtitle-B/chapter-XVII/part-1910/subpart-J/section-1910.147) (via the eCFR Versioner API, `title-29.xml?part=1910`, snapshot date `2024-01-01`) | Public domain (US federal regulation text) | 2026-09-07 |

Scoping rationale is in [`artifacts/system-arch-and-roadmap.md`](../artifacts/system-arch-and-roadmap.md) Sec 1 — this is the anchor source for the demo corpus specifically because it's unambiguously public domain and clause-numbered, unlike the IEC/DIN standards this project is ultimately about (which stay paywalled; only their public front-matter is in scope, not yet ingested).

Extracted with `curl --compressed` against the eCFR Versioner API and isolated to the single `<DIV8 N="1910.147">` section; not modified beyond that extraction.
