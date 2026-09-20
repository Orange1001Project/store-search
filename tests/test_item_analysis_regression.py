"""리팩터링 전후로 03_analyze_items.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

artifacts/reports/item_analysis_stores_v003/item_analysis_summary_stores_v003.json은
리팩터링 전 스크립트가 실제 stores_master_stores_v003.parquet으로 만든 진짜 결과물이다
(SHARE_NOTES.md에 따라 이 요약 json만 남기고 큰 CSV들은 이 공유 폴더에서 제외됐다).
stores_master_*.parquet 자체는 재생성 가능한 중간 산출물이라 로컬에 없으면 이 테스트는
스킵된다 — 02_preprocess_data.py로 재생성하면 실행된다.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.item_analysis import build_item_analysis_report
from store_search_ai.pipeline.common import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
GOLDEN_SUMMARY_PATH = (
    REPO_ROOT / "artifacts" / "reports" / "item_analysis_stores_v003" / "item_analysis_summary_stores_v003.json"
)


def _master_path() -> Path:
    dataset_version = load_config(REPO_ROOT / "configs" / "data" / "default.yaml")["dataset_version"]
    return REPO_ROOT / "data" / "processed" / f"stores_master_{dataset_version}.parquet"


pytestmark = pytest.mark.skipif(
    not _master_path().exists(),
    reason="stores_master_*.parquet 없음 (재생성 가능한 중간 산출물 - 02_preprocess_data.py로 재생성 후 다시 실행)",
)


def test_item_analysis_summary_matches_checked_in_golden_file():
    master_path = _master_path()
    df = pd.read_parquet(master_path)

    report = build_item_analysis_report(df, dataset_name=master_path.name)
    golden = json.loads(GOLDEN_SUMMARY_PATH.read_text(encoding="utf-8"))

    assert report["summary"] == pytest.approx(golden)
