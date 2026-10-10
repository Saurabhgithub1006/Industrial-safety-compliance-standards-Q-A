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
