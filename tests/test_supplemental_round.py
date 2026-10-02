import pandas as pd
import pytest

from store_search_ai.data.annotation_sheets import build_judgment_id
from store_search_ai.data.supplemental_round import (
    build_supplemental_sheet_rows,
    merge_into_base_adjudication,
    select_new_pairs,
    target_queries_with_terms,
)


def _queries():
    return pd.DataFrame(
        {
            "query_id": ["q1", "q2"],
            "query": ["바지 기장 줄이는 곳", "옷 수선"],
            "intent_definition": ["수선", "수선"],
            "split": ["test", "test"],
            "query_family": ["수선", "수선"],
            "query_type": ["T5", "T1"],
            "pool_positive_terms": [None, None],
            "pool_boundary_terms": ["의류 판매", "의류 판매"],
        }
    )


def test_target_queries_with_terms_only_overrides_selected_queries():
    target = target_queries_with_terms(_queries(), ["q1"], ["수선", "옷수선"])
    assert target["query_id"].tolist() == ["q1"]
    assert target.iloc[0]["pool_positive_terms"] == "수선|옷수선"
    assert target.iloc[0]["pool_boundary_terms"] == ""
    with pytest.raises(ValueError, match="없는 query_id"):
        target_queries_with_terms(_queries(), ["q9"], ["수선"])
    with pytest.raises(ValueError, match="비어"):
        target_queries_with_terms(_queries(), ["q1"], [])


def test_select_new_pairs_keeps_only_this_round_and_unjudged():
    pool = pd.DataFrame(
        {
            "query_id": ["q1", "q1", "q1", "q2"],
            "doc_id": ["d_old", "d_new", "d_judged", "d_new"],
            "first_seen_round": ["lexical_v1", "supplement_v1", "supplement_v1", "supplement_v1"],
        }
    )
    judged = {build_judgment_id("q1", "d_judged")}
    new = select_new_pairs(pool, "supplement_v1", ["q1"], judged)
    assert new["doc_id"].tolist() == ["d_new"]
    assert new.iloc[0]["judgment_id"] == build_judgment_id("q1", "d_new")


def test_build_supplemental_sheet_rows_adds_metadata_and_empty_fields():
    pairs = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "judgment_id": ["j1"]})
    rows = build_supplemental_sheet_rows(pairs, _queries(), "supplement_v1")
    row = rows.iloc[0]
    assert row["query"] == "바지 기장 줄이는 곳" and row["split"] == "test"
    assert row["annotation_round"] == "supplement_v1" and row["relevance"] == ""


def test_merge_appends_new_rows_replaces_same_round_and_protects_base():
    base = pd.DataFrame({"judgment_id": ["a", "b"], "final_relevance": [3, 0]})
    sup = pd.DataFrame({"judgment_id": ["c"], "final_relevance": [2], "supplemental_round": ["supplement_v1"]})

    merged = merge_into_base_adjudication(base, sup)
    assert merged["judgment_id"].tolist() == ["a", "b", "c"]
    assert merged["supplemental_round"].isna().tolist() == [True, True, False]

    # 같은 라운드를 다시 merge하면 그 라운드 행만 교체
    sup2 = pd.DataFrame({"judgment_id": ["c"], "final_relevance": [3], "supplemental_round": ["supplement_v1"]})
    again = merge_into_base_adjudication(merged, sup2)
    assert again["judgment_id"].tolist() == ["a", "b", "c"]
    assert again.loc[again["judgment_id"] == "c", "final_relevance"].item() == 3

    # 원래 판정과 겹치면 에러(기존 판정은 바꾸지 않음)
    clash = pd.DataFrame({"judgment_id": ["a"], "final_relevance": [1], "supplemental_round": ["supplement_v1"]})
    with pytest.raises(ValueError, match="겹칩니다"):
        merge_into_base_adjudication(base, clash)
