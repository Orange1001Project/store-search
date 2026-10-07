"""공식 evaluator(build_evaluation_report)의 결과가 저장소에 커밋된 평가 결과와 동일한지 확인하는 golden-file 회귀 테스트.

artifacts/evaluation/storesearch_ko_v1/*_evaluation.json은 확정 gold qrels(qrels_val.trec)로
results/model_eval/*/run_*.csv를 채점한 실제 결과다(Colab에서 채점 → import_colab_results.py --verify로
로컬 evaluator와 일치 확인 후 커밋). 이 테스트는 같은 입력·같은 seed로 evaluator를 다시 돌려 aggregate 지표와
bootstrap CI가 완전히 같은지 검증한다 — evaluator나 qrels가 바뀌면 여기서 실패한다.
"""

import json
from pathlib import Path

import pytest

from store_search_ai.evaluation.evaluator import build_evaluation_report

REPO_ROOT = Path(__file__).resolve().parents[1]
QRELS_VAL = REPO_ROOT / "benchmark" / "storesearch_ko_v1" / "qrels_val.trec"
RESULTS_DIR = REPO_ROOT / "results" / "model_eval"
GOLDEN_EVAL_DIR = REPO_ROOT / "artifacts" / "evaluation" / "storesearch_ko_v1"

# (tag_dir, template) -> eval_tag은 15_score_model_runs.py와 동일하게 f"{tag}_{template}_val"
GOLDEN_RUNS = [
    ("qwen3_embedding_0_6b", "t1_minimal"),
    ("qwen3_embedding_0_6b_ft_kse1_20261006_0708", "t1_minimal"),
]

pytestmark = pytest.mark.skipif(
    not QRELS_VAL.exists(), reason="benchmark/storesearch_ko_v1/qrels_val.trec 없음"
)


@pytest.mark.parametrize("tag,template", GOLDEN_RUNS)
def test_evaluation_matches_checked_in_golden_report(tag, template):
    eval_tag = f"{tag}_{template}_val"
    run_path = RESULTS_DIR / tag / f"run_{template}_val.csv"
    golden_path = GOLDEN_EVAL_DIR / f"{eval_tag}_evaluation.json"

    if not run_path.exists() or not golden_path.exists():
        # results/model_eval/은 git에 없는 재생성 산출물 — 그 run을 채점한 golden과 짝이 맞을 때만 비교한다
        pytest.skip(f"run 또는 golden 없음: {run_path.name} / {golden_path.name}")

    golden = json.loads(golden_path.read_text(encoding="utf-8"))

    report, _ = build_evaluation_report(
        qrels_path=QRELS_VAL,
        run_path=run_path,
        tag=eval_tag,
        bootstrap_samples=10000,
        seed=20260831,
    )

    assert report["aggregate"] == pytest.approx(golden["aggregate"])
    assert report["query_count"] == golden["query_count"]
    assert report["run_query_count"] == golden["run_query_count"]

    for metric, golden_ci in golden["query_bootstrap_ci95"].items():
        got_ci = report["query_bootstrap_ci95"][metric]
        assert got_ci["mean"] == pytest.approx(golden_ci["mean"])
        assert got_ci["ci95"] == pytest.approx(golden_ci["ci95"])
