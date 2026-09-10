"""Phase 4 CLI: run the adversarial eval set against a live Judge 1 and report
precision/recall/accuracy per verdict class.

    PYTHONPATH=src python -m safety_qa.judging.run_judge_eval

Needs a real LLM API key in .env and the ingested corpus (data/processed/corpus.db)
-- see eval_set.py for why this can't be a pure-Python/CI-enforced check the way
Phase 2's recall@k was. Provider defaults to Kimi (small/fast tier: kimi-k2.6) --
set LLM_PROVIDER=anthropic in .env to use Claude Haiku instead; see
llm_client.build_client().
"""

from __future__ import annotations

from pathlib import Path

from safety_qa.generation.llm_client import build_client
from safety_qa.ingestion.store import connect

from .eval_set import ADVERSARIAL_SET, precision_recall
from .grounding_judge import GroundingJudge

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_DB_PATH = str(_REPO_ROOT / "data" / "processed" / "corpus.db")


def run(db_path: str = _DEFAULT_DB_PATH) -> None:
    conn = connect(db_path)
    judge = GroundingJudge(conn, build_client("judge"))

    claims = [case.claim for case in ADVERSARIAL_SET]
    judged = judge.evaluate_claims(claims)
    judged_by_id = {jc.claim.claim_id: jc for jc in judged}

    predicted = []
    expected = []
    print(f"{'case':55} {'expected':13} {'got':13} {'ok'}")
    for case in ADVERSARIAL_SET:
        jc = judged_by_id[case.claim.claim_id]
        predicted.append(jc.verdict)
        expected.append(case.expected_verdict)
        ok = "OK" if jc.verdict == case.expected_verdict else "MISS"
        print(f"{case.description[:55]:55} {case.expected_verdict:13} {jc.verdict:13} {ok}")
        if ok == "MISS":
            print(f"    reasoning: {jc.reasoning}")

    report = precision_recall(predicted, expected)
    print(f"\naccuracy: {report['accuracy']:.2%}")
    for label in ("supported", "contradicted", "unsupported"):
        r = report[label]
        p = f"{r['precision']:.2%}" if r["precision"] is not None else "n/a"
        rec = f"{r['recall']:.2%}" if r["recall"] is not None else "n/a"
        print(f"  {label:13} precision={p:>7}  recall={rec:>7}  (n={r['support']})")


if __name__ == "__main__":
    run()
