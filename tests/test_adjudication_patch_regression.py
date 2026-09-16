"""리팩터링 전후로 10_apply_adjudication_patch.py의 산출물이 동일한지 확인하는 golden-file
회귀 테스트.

이 스크립트의 실제 입력(adjudication_val_test_full.csv,
adjudication_val_test_needed_only_completed.csv - 3rd adjudicator가 직접 채운 원본)과 출력
(adjudication_val_test_full_completed.csv)이 전부 이 공유 폴더에 체크인돼 있어서, 파이프라인
재생성 없이 바로 검증할 수 있다.
"""

from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.adjudication_patch import apply_adjudication_patch

REPO_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = (
    REPO_ROOT / "benchmark" / "storesearch_ko_v1" / "annotations" / "full_annotation_v1" / "analysis"
)
FULL_PATH = ANALYSIS_DIR / "adjudication_val_test_full.csv"
PATCH_PATH = ANALYSIS_DIR / "adjudication_val_test_needed_only_completed.csv"
GOLDEN_OUTPUT_PATH = ANALYSIS_DIR / "adjudication_val_test_full_completed.csv"

pytestmark = pytest.mark.skipif(
    not FULL_PATH.exists() or not PATCH_PATH.exists() or not GOLDEN_OUTPUT_PATH.exists(),
    reason="adjudication 원본/patch/golden 산출물 없음",
)


def test_apply_adjudication_patch_matches_checked_in_golden_file(tmp_path):
    full = pd.read_csv(FULL_PATH, encoding="utf-8-sig")
    patch = pd.read_csv(PATCH_PATH, encoding="utf-8-sig")

    result = apply_adjudication_patch(full, patch)

    written_path = tmp_path / "adjudication_val_test_full_completed.csv"
    result.to_csv(written_path, index=False, encoding="utf-8-sig")

    assert written_path.read_bytes() == GOLDEN_OUTPUT_PATH.read_bytes()
