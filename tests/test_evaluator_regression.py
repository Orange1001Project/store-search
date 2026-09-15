"""리팩터링 전후로 13_evaluate_run.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

artifacts/evaluation/storesearch_ko_v1/*_evaluation.json은 리팩터링 전 스크립트가 실제
results/model_eval/*/run_*.csv (사람 애노테이션으로 만든 qrels_val.trec 기준)를 채점해서
만든 진짜 결과물이다 — 방금 만든 회의 노트의 리더보드 숫자와 동일한 파일. 이 테스트는
리팩터링된 build_evaluation_report()를 같은 입력·같은 seed로 실행해서 aggregate 지표와
bootstrap CI가 완전히 동일한지 검증한다.
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
    ("bge_m3", "t1_minimal"),
    ("qwen3_embedding_0_6b", "t1_minimal"),
    ("snowflake_arctic_embed_l_v2_ko", "t1_minimal"),
    ("snowflake_arctic_embed_l_v2_ko", "t2_market"),
]

pytestmark = pytest.mark.skipif(
    not QRELS_VAL.exists(), reason="benchmark/storesearch_ko_v1/qrels_val.trec 없음"
)


@pytest.mark.parametrize("tag,template", GOLDEN_RUNS)
def test_evaluation_matches_checked_in_golden_report(tag, template):
    eval_tag = f"{tag}_{template}_val"
    run_path = RESULTS_DIR / tag / f"run_{template}_val.csv"
    golden_path = GOLDEN_EVAL_DIR / f"{eval_tag}_evaluation.json"

    assert run_path.exists(), f"run 파일 없음: {run_path}"
    assert golden_path.exists(), f"golden 파일 없음: {golden_path}"

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
