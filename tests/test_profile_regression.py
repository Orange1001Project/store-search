"""리팩터링 전후로 01_profile_data.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

data/raw/stores_20260907.xlsx(원본, 재생성 불가라 이 공유 폴더에 항상 있음)와
artifacts/reports/data_profile.json(golden, 체크인됨)만 있으면 되므로 파이프라인 재생성이
필요 없다.
"""

import json
from pathlib import Path

import pytest

from store_search_ai.common.io import load_yaml, read_excel_sheets
from store_search_ai.data.profile import build_data_profile_report

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_PATH = REPO_ROOT / "data" / "raw" / "stores_20260907.xlsx"
CONFIG_PATH = REPO_ROOT / "configs" / "data" / "default.yaml"
GOLDEN_PATH = REPO_ROOT / "artifacts" / "reports" / "data_profile.json"

pytestmark = pytest.mark.skipif(not RAW_PATH.exists(), reason="data/raw/stores_20260907.xlsx 없음")


def test_profile_report_matches_checked_in_golden_file():
    config = load_yaml(CONFIG_PATH)
    sheets = read_excel_sheets(RAW_PATH, config["excel"]["sheets"])

    result = build_data_profile_report(sheets, input_name=RAW_PATH.name)
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    assert result == golden
