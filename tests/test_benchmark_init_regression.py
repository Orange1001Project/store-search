"""리팩터링 전후로 05_init_benchmark.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

configs/benchmark/query_families_v1.yaml(입력)과 benchmark/storesearch_ko_v1/queries.csv,
annotation_guideline.md, query_manifest.json(출력)이 전부 이 공유 폴더에 체크인돼 있어서,
파이프라인 재생성 없이 바로 검증할 수 있다.
"""

from pathlib import Path

import pytest

from store_search_ai.data.benchmark_init import (
    GUIDELINE,
    build_queries_frame,
    build_query_manifest,
)
from store_search_ai.pipeline.common import load_config, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "benchmark" / "storesearch_ko_v1.yaml"
FAMILIES_PATH = REPO_ROOT / "configs" / "benchmark" / "query_families_v1.yaml"
BENCHMARK_DIR = REPO_ROOT / "benchmark" / "storesearch_ko_v1"
GOLDEN_QUERIES_PATH = BENCHMARK_DIR / "queries.csv"
GOLDEN_GUIDELINE_PATH = BENCHMARK_DIR / "annotation_guideline.md"
GOLDEN_MANIFEST_PATH = BENCHMARK_DIR / "query_manifest.json"

pytestmark = pytest.mark.skipif(
    not FAMILIES_PATH.exists() or not GOLDEN_QUERIES_PATH.exists(),
    reason="query_families_v1.yaml/queries.csv 없음",
)


def test_init_benchmark_matches_checked_in_golden_files(tmp_path):
    config = load_config(CONFIG_PATH)
    query_cfg = load_config(FAMILIES_PATH)

    queries = build_queries_frame(query_cfg)

    written_queries_path = tmp_path / "queries.csv"
    queries.to_csv(written_queries_path, index=False, encoding="utf-8-sig")
    assert written_queries_path.read_bytes() == GOLDEN_QUERIES_PATH.read_bytes()

    assert GUIDELINE == GOLDEN_GUIDELINE_PATH.read_text(encoding="utf-8")

    manifest = build_query_manifest(
        config=config,
        query_cfg=query_cfg,
        queries=queries,
        queries_sha256=sha256_file(written_queries_path),
        families_config_sha256=sha256_file(FAMILIES_PATH),
    )

    import json

    golden_manifest = json.loads(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest == golden_manifest
