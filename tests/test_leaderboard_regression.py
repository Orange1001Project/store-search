"""리팩터링 전후로 15_score_model_runs.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

results/model_eval/*/run_*_val.csv, artifacts/evaluation/storesearch_ko_v1/*_evaluation.json
(13_evaluate_run.py가 이미 만들어 둔 실제 채점 결과), results/model_eval/leaderboard_val.csv가
전부 이 공유 폴더에 체크인돼 있어서, subprocess로 13번을 다시 부르지 않고 이미 있는
evaluation.json만 읽어 리더보드 조립 로직만 검증한다(13번 자체는 tests/test_evaluator_regression.py
에서 이미 별도로 검증됨).
"""

import json
from pathlib import Path

import pytest

from store_search_ai.models.leaderboard import build_leaderboard, find_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results" / "model_eval"
EVAL_DIR = REPO_ROOT / "artifacts" / "evaluation" / "storesearch_ko_v1"
GOLDEN_LEADERBOARD_PATH = RESULTS_DIR / "leaderboard_val.csv"

pytestmark = pytest.mark.skipif(
    not GOLDEN_LEADERBOARD_PATH.exists(), reason="results/model_eval/leaderboard_val.csv 없음"
)


def test_leaderboard_matches_checked_in_golden_file(tmp_path):
    runs = list(find_runs(RESULTS_DIR, "val"))
    assert runs, "no runs found under results/model_eval"

    rows = []
    for tag, template, _run_path in runs:
        eval_tag = f"{tag}_{template}_val"
        report = json.loads((EVAL_DIR / f"{eval_tag}_evaluation.json").read_text(encoding="utf-8"))
        row = {"tag": tag, "template": template}
        row.update(report["aggregate"])
        rows.append(row)

    leaderboard = build_leaderboard(rows)

    written_path = tmp_path / "leaderboard_val.csv"
    leaderboard.to_csv(written_path, index=False, encoding="utf-8-sig", lineterminator="\n")

    assert written_path.read_bytes() == GOLDEN_LEADERBOARD_PATH.read_bytes()
