import numpy as np
import pandas as pd

from store_search_ai.data.service_queryset import (
    absent_candidate_counts,
    brand_token,
    chain_candidates,
    is_name_only,
    item_gap_candidates,
    sample_stores,
    split_items,
)


def _corpus() -> pd.DataFrame:
    names = ["지에스25 강남점", "GS25 역삼점", "(주)씨유 서초점", "CU 방배점", "형제상회", "형제상회", "맛집", np.nan]
    items = ["편의점", "편의점", "편의점", "편의점", "건어물", "보청기", "음식점", np.nan]
    n = len(names)
    return pd.DataFrame(
        {
            "doc_id": [f"d{i}" for i in range(n)],
            "store_name": names,
            "item_text": items,
            "market_name": ["m"] * n,
            "market_type": ["전통시장", "전통시장", "골목형상점가", "골목형상점가"] * 2,
            "address": ["서울특별시 강남구 어딘가"] * n,
            "latitude": [37.5] * n,
            "longitude": [127.0] * n,
            "geo_status": ["VALID"] * n,
            "source_region": ["서울특별시"] * n,
        }
    )


def test_split_items_and_name_only_handle_missing_values():
    assert split_items("한식, 분식/김밥") == ["한식", "분식", "김밥"]
    assert split_items(np.nan) == []
    assert is_name_only(np.nan, {"음식점"}) is True
    assert is_name_only("음식점", {"음식점"}) is True
    assert is_name_only("음식점, 치킨", {"음식점"}) is False


def test_brand_token_strips_corporate_prefix():
    assert brand_token("(주)씨유 서초점") == "씨유"
    assert brand_token(np.nan) == ""


def test_chain_candidates_merges_aliases_and_marks_common_names():
    out = chain_candidates(
        _corpus(), {"GS25": ["GS25", "지에스25"], "CU": ["CU", "씨유"]}, [], ["상회"], min_count=2
    ).set_index("브랜드")
    assert out.loc["GS25", "가맹점수"] == 2
    assert out.loc["CU", "가맹점수"] == 2
    assert out.loc["형제상회", "구분"] == "동명 가맹점(흔한 상호)"
    assert out.loc["GS25", "구분"] == "체인 후보"


def test_item_gap_candidates_skips_covered_and_generic_items():
    out = item_gap_candidates(_corpus(), {"편의점", "건어물"}, {"음식점"}, top_n=10)
    assert out["업종·품목"].tolist() == ["보청기"]


def test_sample_stores_is_deterministic_and_respects_name_only_share():
    corpus = _corpus()
    a = sample_stores(corpus, n=4, name_only_share=0.5, generic_items={"음식점"}, seed=1)
    b = sample_stores(corpus, n=4, name_only_share=0.5, generic_items={"음식점"}, seed=1)
    assert a["doc_id"].tolist() == b["doc_id"].tolist()
    assert (a["층"] == "상호명만").sum() == 2


def test_absent_candidate_counts_flags_present_words():
    out = absent_candidate_counts(_corpus(), ["코스트코", "편의점"]).set_index("질의 후보")
    assert out.loc["코스트코", "판단"] == "E로 사용 가능"
    assert out.loc["편의점", "코퍼스 출현 수"] == 4
