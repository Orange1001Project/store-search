"""리팩터링 전후로 import_queryset_xlsx.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

configs/benchmark/query_families_v1.yaml은 리팩터링 전 스크립트(하드코딩된
RECLASSIFY_QUERIES/RANDOM_SEED)가 실제로 만들어낸 결과물이다. 이 테스트는 리팩터링된
build_query_families()를 같은 입력(같은 xlsx, 같은 corrections yaml로 옮긴 동일한 값,
같은 seed)으로 실행해서 그 결과물과 완전히 동일한 dict가 나오는지 검증한다 — split
상속 로직 때문에 모든 family가 이미 golden 파일에 존재하므로, 이 비교는 seed 자체보다는
재배정/텍스트 추출 로직이 안 깨졌는지를 검증하는 역할이 크다.
"""

from pathlib import Path

import pandas as pd
import pytest
import yaml

from store_search_ai.data.query_import import build_query_families, parse_corrections
from store_search_ai.pipeline.common import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
QUERYSET_XLSX = REPO_ROOT / "data" / "query" / "queryset_final.xlsx"
GOLDEN_FAMILIES_YAML = REPO_ROOT / "configs" / "benchmark" / "query_families_v1.yaml"
BENCHMARK_CONFIG = REPO_ROOT / "configs" / "benchmark" / "storesearch_ko_v1.yaml"

pytestmark = pytest.mark.skipif(
    not QUERYSET_XLSX.exists(),
    reason="data/query/queryset_final.xlsx 없음 (팀 공유 폴더에는 포함되어 있어야 함)",
)


def test_build_query_families_matches_checked_in_golden_file():
    config = load_config(BENCHMARK_CONFIG)
    query_set_config = config["query_set"]

    corrections_raw = load_config(REPO_ROOT / query_set_config["corrections_path"])
    reclassify_queries, ambiguous_slugs = parse_corrections(corrections_raw)

    golden = yaml.safe_load(GOLDEN_FAMILIES_YAML.read_text(encoding="utf-8"))
    existing_split_by_family = {fam["family"]: fam["split"] for fam in golden["families"]}

    xls = pd.ExcelFile(QUERYSET_XLSX)
    queries = xls.parse("통합질의")
    fam_list = xls.parse("패밀리목록")

    output = build_query_families(
        queries=queries,
        fam_list=fam_list,
        existing_split_by_family=existing_split_by_family,
        reclassify_queries=reclassify_queries,
        ambiguous_slugs=ambiguous_slugs,
        random_seed=query_set_config["random_seed"],
        query_set_version=query_set_config["version"],
    )

    assert output == golden
