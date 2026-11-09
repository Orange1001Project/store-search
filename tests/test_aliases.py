import sys
from pathlib import Path

import pandas as pd

from store_search_ai.query.aliases import BrandAliases, brand_store

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from eval_service_pipeline import alias_name_hits, brand_distance_sort

TABLE = pd.DataFrame({"brand": ["GS25", "GS25", "CU", "CU", "파리바게뜨", "파리바게뜨"],
                      "variant": ["gs25", "지에스25", "cu", "씨유", "파리바게뜨", "파리바게트"]})


def test_variants_group_and_short_names_match_prefix_only():
    a = BrandAliases(TABLE)
    assert a.variants("GS25") == {"gs25", "지에스25"}
    assert a.variants("파리바게트") == {"파리바게뜨", "파리바게트"}
    assert a.variants("없는브랜드") == {"없는브랜드"}
    assert brand_store(a.variants("CU"), "씨유 신림점") and brand_store(a.variants("cu"), "CU역삼점")
    assert not brand_store(a.variants("CU"), "스쿠버cu샵")          # 2글자 표기는 상호 앞부분만
    assert brand_store(a.variants("GS25"), "지에스25 봉천점")


def test_alias_name_hits_catch_other_spelling():
    run = pd.DataFrame({"query_id": ["i1", "i1", "i1"], "doc_id": ["a", "b", "c"]})
    names = pd.Series({"a": "지에스25 봉천점", "b": "GS25 서원점", "c": "세븐일레븐"})
    hits = alias_name_hits(run, {"i1": "GS25"}, names, BrandAliases(TABLE))
    assert hits.tolist() == [True, True, False]


def test_brand_distance_sort_puts_nearest_branch_first_and_adds_missing_branches():
    instances = pd.DataFrame({"instance_id": ["b1", "c1"], "latitude": [37.5, 37.5], "longitude": [127.0, 127.0]})
    corpus = pd.DataFrame({"doc_id": ["far", "near", "other", "missing"],
                           "store_name": ["GS25 먼점", "지에스25 가까운점", "동네슈퍼", "GS25 새점"],
                           "latitude": [37.508, 37.501, 37.5, 37.504], "longitude": [127.0, 127.0, 127.0, 127.0]})
    run = pd.DataFrame({"query_id": ["b1", "b1", "b1", "c1", "c1"], "doc_id": ["other", "far", "near", "other", "far"],
                        "score": [1.2, 1.1, 0.3, 0.9, 0.1], "rank": [1, 2, 3, 1, 2]})
    parsed = pd.DataFrame({"instance_id": ["b1", "c1"], "core": ["GS25", "슈퍼"], "intent": ["brand", "category"]})
    out = brand_distance_sort(run, instances, parsed, corpus, BrandAliases(TABLE), 2.0, "x")
    b1 = out[out["query_id"] == "b1"].sort_values("rank")["doc_id"].tolist()
    assert b1 == ["near", "missing", "far", "other"]          # 지점(별칭 포함, 후보에 없던 것도) 가까운 순 → 나머지
    assert out[out["query_id"] == "c1"].sort_values("rank")["doc_id"].tolist() == ["other", "far"]   # 브랜드 아닌 쿼리는 그대로
