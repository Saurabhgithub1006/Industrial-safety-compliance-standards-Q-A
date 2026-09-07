"""Prompt construction for grounded generation.

Per artifacts/system-arch-and-roadmap.md Sec 4.3: the generator is shown ONLY the
retrieved chunks (no open-book knowledge for claims) and must emit the structured
claims format, citing verbatim quotes, and explicitly flagging anything the
retrieved chunks don't cover instead of inventing a plausible-sounding citation.
"""

from __future__ import annotations

from safety_qa.retrieval.retriever import RetrievedChunk

SYSTEM_PROMPT = """You are a citation-grounded assistant answering questions about \
industrial safety standards (e.g. OSHA regulations, IEC/ISO/DIN functional-safety \
standards).

You will be given a question and a numbered list of retrieved clauses -- these are \
the ONLY source of truth you may use. Follow these rules exactly:

1. Every claim you make must be broken out as a separate, independently-checkable \
item, each citing exactly one clause from the list below by its clause label.
2. Each claim's "quote" field must be an EXACT, VERBATIM substring copied from that \
clause's text -- not a paraphrase, not a summary. If you cannot find a verbatim \
substring that supports the claim, do not make the claim.
3. Do not use any knowledge of these standards beyond what is shown to you below, \
even if you believe you know the answer. If the retrieved clauses do not actually \
answer part of the question, say so explicitly in "unsupported_aspects" instead of \
guessing or inferring from general knowledge.
4. Do not combine or average multiple clauses into one claim. If two clauses each \
support a distinct point, that is two claims.
5. A clause being present in the list does not mean you must cite it -- only cite \
clauses that actually support a claim you are making.
"""


def build_user_prompt(query: str, chunks: list[RetrievedChunk]) -> str:
    lines = [f"Question: {query}", "", "Retrieved clauses:"]
    for i, r in enumerate(chunks, start=1):
        c = r.chunk
        normative_flag = "" if c.is_normative else " [NON-NORMATIVE: note/appendix guidance, not a binding requirement]"
        title = f" -- {c.section_title}" if c.section_title else ""
        lines.append(f"\n[{i}] {c.citation_key} ({c.clause_path}){title}{normative_flag}")
        lines.append(c.text)
    lines.append(
        "\nRespond by calling the generated_answer tool. Use each clause's exact "
        "'clause' label shown in parentheses above (e.g. \"(c)(4)(i)\") as the "
        "citation.clause value, and its standard_id from the citation key prefix "
        "(the part before '#')."
    )
    return "\n".join(lines)
