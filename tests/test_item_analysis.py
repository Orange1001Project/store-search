import pandas as pd
import pytest

from store_search_ai.data.item_analysis import (
    build_item_analysis_report,
    build_raw_value_counts,
    build_regional_token_counts,
    build_token_counts,
    clean_html_entity_items,
    explode_item_tokens,
    has_unbalanced_parentheses,
    html_entity_items,
    item_conflict_stores,
    long_item_values,
    low_information_tokens,
    missing_item_stores,
    noise_token_candidates,
    token_coverage,
    unbalanced_parentheses_items,
)


def _master(**overrides):
    base = pd.DataFrame(
        [
            {
                "store_id": "s1", "store_name": "치킨집", "market_name": "", "market_type": "",
                "address": "서울", "source_region": "서울", "item_raw": "치킨,통닭",
                "item_text": "치킨, 통닭", "item_tokens": ["치킨", "통닭"], "has_item": True,
            },
            {
                "store_id": "s2", "store_name": "빵집", "market_name": "", "market_type": "",
                "address": "부산", "source_region": "부산", "item_raw": None,
                "item_text": None, "item_tokens": [], "has_item": False,
            },
        ]
    )
    for key, value in overrides.items():
        base[key] = value
    return base


def test_has_unbalanced_parentheses_detects_mismatch():
    assert has_unbalanced_parentheses("치킨(반마리") is True
    assert has_unbalanced_parentheses("치킨)반마리(") is True
    assert has_unbalanced_parentheses("치킨(반마리)") is False


def test_has_unbalanced_parentheses_handles_none_and_nan():
    assert has_unbalanced_parentheses(None) is False
    assert has_unbalanced_parentheses(float("nan")) is False


def test_explode_item_tokens_drops_blank_and_missing():
    df = _master()
    token_df = explode_item_tokens(df)
    assert list(token_df["item"]) == ["치킨", "통닭"]


def test_build_token_counts_counts_occurrences():
    df = pd.DataFrame({"store_id": ["a", "b"], "source_region": ["s", "s"], "item_tokens": [["치킨"], ["치킨"]]})
    token_df = explode_item_tokens(df)
    counts = build_token_counts(token_df)
    assert counts.set_index("item")["count"].to_dict() == {"치킨": 2}


def test_build_raw_value_counts_strips_and_counts():
    df = pd.DataFrame({"item_raw": [" 치킨 ", "치킨", None]})
    counts = build_raw_value_counts(df)
    assert counts.set_index("item_raw")["count"].to_dict() == {"치킨": 2}


def test_build_regional_token_counts_groups_by_region():
    df = pd.DataFrame(
        {"store_id": ["a", "b"], "source_region": ["서울", "부산"], "item_tokens": [["치킨"], ["빵"]]}
    )
    token_df = explode_item_tokens(df)
    regional = build_regional_token_counts(token_df)
    assert set(zip(regional["source_region"], regional["item"])) == {("서울", "치킨"), ("부산", "빵")}


def test_missing_item_stores_filters_has_item_false():
    df = _master()
    result = missing_item_stores(df)
    assert list(result["store_id"]) == ["s2"]


def test_item_conflict_stores_returns_none_without_column():
    assert item_conflict_stores(_master()) is None


def test_item_conflict_stores_filters_flagged_rows():
    df = _master(item_conflict=[True, False], item_raw_variants=["a|b", ""])
    result = item_conflict_stores(df)
    assert list(result["store_id"]) == ["s1"]


def test_long_item_values_filters_by_length_and_adds_length_column():
    df = _master()
    df.loc[0, "item_raw"] = "x" * 80
    result = long_item_values(df, min_length=80)
    assert list(result["store_id"]) == ["s1"]
    assert result.iloc[0]["item_raw_length"] == 80


def test_unbalanced_parentheses_items_filters_correctly():
    df = _master()
    df.loc[0, "item_raw"] = "치킨(반마리"
    result = unbalanced_parentheses_items(df)
    assert list(result["store_id"]) == ["s1"]


def test_html_entity_items_and_clean_html_entity_items():
    df = _master()
    df.loc[0, "item_raw"] = "치킨&amp;통닭"
    df.loc[0, "item_text"] = "치킨"
    raw_hits = html_entity_items(df)
    clean_hits = clean_html_entity_items(df)
    assert list(raw_hits["store_id"]) == ["s1"]
    assert list(clean_hits["store_id"]) == []


def test_noise_token_candidates_matches_punct_only_and_literals():
    counts = pd.DataFrame({"item": ["치킨", "-", "...", "amp"], "count": [5, 1, 1, 1]})
    result = noise_token_candidates(counts)
    assert set(result["item"]) == {"-", "...", "amp"}


def test_low_information_tokens_matches_curated_terms():
    counts = pd.DataFrame({"item": ["치킨", "기타", "서비스"], "count": [5, 1, 1]})
    result = low_information_tokens(counts)
    assert set(result["item"]) == {"기타", "서비스"}


def test_token_coverage_zero_total_returns_zero():
    counts = pd.DataFrame({"item": [], "count": []})
    assert token_coverage(counts, 10, total_token_occurrences=0) == 0.0


def test_token_coverage_computes_top_n_share():
    counts = pd.DataFrame({"item": ["a", "b", "c"], "count": [6, 3, 1]})
    assert token_coverage(counts, 1, total_token_occurrences=10) == pytest.approx(0.6)
    assert token_coverage(counts, 2, total_token_occurrences=10) == pytest.approx(0.9)


def test_build_item_analysis_report_end_to_end_schema():
    df = _master()
    report = build_item_analysis_report(df, dataset_name="test.parquet")

    assert set(report) == {
        "item_token_counts", "item_raw_counts", "item_token_counts_by_region",
        "missing_item_stores", "item_conflict_stores", "long_item_values",
        "unbalanced_parentheses", "html_entity_items", "clean_html_entity_items",
        "low_information_tokens", "summary",
    }
    assert report["item_conflict_stores"] is None

    summary = report["summary"]
    assert summary["dataset"] == "test.parquet"
    assert summary["master_store_rows"] == 2
    assert summary["item_present_rows"] == 1
    assert summary["item_missing_rows"] == 1
    assert summary["item_missing_rate"] == pytest.approx(0.5)
    assert summary["unique_tokens"] == 2
    assert summary["item_conflict_stores"] == 0
