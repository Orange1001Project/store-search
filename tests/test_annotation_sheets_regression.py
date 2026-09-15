"""리팩터링 전후로 08_make_full_annotation_sheets.py의 산출물이 동일한지 확인하는
golden-file 회귀 테스트.

benchmark/storesearch_ko_v1/annotations/full_annotation_v1/annotation_A_all.csv,
annotation_manifest.json은 리팩터링 전 스크립트가 실제 candidate_pool_internal.csv +
queries.csv로 만든 진짜 결과물이다. candidate_pool_internal.csv 자체는 이 공유 폴더에서는
재생성 가능한 중간 산출물이라 빠져 있으므로(SHARE_NOTES.md), 이 테스트는 그 파일이 로컬에
재생성되어 있을 때만 실행된다 - 없으면 스킵된다.

주의: 01~07을 실제로 재실행해서 검증해본 결과, candidate_pool_internal.csv가
SHARE_NOTES.md의 주장과 달리 바이트 단위로 재현되지 않는 것을 확인했다(재생성한 pool이
55647행, 체크인된 pool_history.csv 기록은 61619행 - lexical run 계산 어딘가에 비결정성이
있는 것으로 보이며 이 리팩터링과는 무관한 별개의 기존 이슈). 그래서 이 테스트가 실패하더라도
곧바로 리팩터링 버그로 해석하지 말 것 - 08_make_full_annotation_sheets.py 리팩터링 자체의
동일성은 이 테스트가 아니라, 리팩터링 전/후 스크립트를 같은 재생성된 pool에 대해 직접 실행해
8개 출력 파일을 diff하는 방식으로 별도 검증했다(전부 IDENTICAL 확인).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.annotation_sheets import (
    build_annotation_manifest,
    build_annotator_frame,
    build_split_stats,
    prepare_pool,
)
from store_search_ai.pipeline.common import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmark" / "storesearch_ko_v1"
POOL_PATH = BENCHMARK_DIR / "candidate_pool_internal.csv"
QUERIES_PATH = BENCHMARK_DIR / "queries.csv"
GOLDEN_DIR = BENCHMARK_DIR / "annotations" / "full_annotation_v1"

pytestmark = pytest.mark.skipif(
    not POOL_PATH.exists(),
    reason=(
        "candidate_pool_internal.csv 없음 (재생성 가능한 중간 산출물 - "
        "docs/PIPELINE.md 1~3절로 재생성 후 다시 실행)"
    ),
)


def test_annotation_sheets_match_checked_in_golden_files():
    config = load_config(REPO_ROOT / "configs" / "benchmark" / "storesearch_ko_v1.yaml")

    pool = pd.read_csv(POOL_PATH)
    queries = pd.read_csv(QUERIES_PATH)
    queries = queries[queries["status"] == "active"].copy()

    pool = prepare_pool(pool, queries, "full_annotation_v1")
    seed = int(config["annotation"]["random_seed"])

    a = build_annotator_frame(pool, seed, "A")
    b = build_annotator_frame(pool, seed, "B", splits=["val", "test"])

    golden_a = pd.read_csv(GOLDEN_DIR / "annotation_A_all.csv", encoding="utf-8-sig")
    golden_b = pd.read_csv(GOLDEN_DIR / "annotation_B_val_test.csv", encoding="utf-8-sig")

    from store_search_ai.data.annotation_sheets import VISIBLE_COLUMNS

    pd.testing.assert_frame_equal(
        a[VISIBLE_COLUMNS].reset_index(drop=True), golden_a.reset_index(drop=True)
    )
    pd.testing.assert_frame_equal(
        b[VISIBLE_COLUMNS].reset_index(drop=True), golden_b.reset_index(drop=True)
    )

    split_stats = build_split_stats(pool)
    manifest = build_annotation_manifest("full_annotation_v1", queries, a, b, split_stats)
    golden_manifest = json.loads((GOLDEN_DIR / "annotation_manifest.json").read_text(encoding="utf-8"))

    assert manifest == golden_manifest
