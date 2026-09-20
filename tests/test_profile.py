import pandas as pd

from store_search_ai.data.profile import build_data_profile_report, profile_frame


def test_profile_frame_reports_basic_stats():
    df = pd.DataFrame({"a": [1, None, 3], "b": ["x", "y", "x"]})
    report = profile_frame(df, source="test")
    assert report["source"] == "test"
    assert report["rows"] == 3
    assert report["columns"] == ["a", "b"]
    assert report["null_count"] == {"a": 1, "b": 0}
    assert report["unique_count"] == {"a": 2, "b": 2}


def test_profile_frame_detects_duplicate_business_no():
    df = pd.DataFrame({"사업자번호": ["123-45-6789", "1234 56789", "999"]})
    report = profile_frame(df, source="test")
    assert report["business_no_duplicate_rows"] == 2  # first two normalize to the same digits


def test_profile_frame_reports_missing_merchant_no():
    df = pd.DataFrame({"가맹점번호": ["1", "", None, "  "]})
    report = profile_frame(df, source="test")
    assert report["merchant_no_missing"] == 3


def test_profile_frame_reports_item_missing_rate_and_top_items():
    df = pd.DataFrame({"취급품목": ["치킨", "치킨", None, ""]})
    report = profile_frame(df, source="test")
    assert report["item_missing_rows"] == 2
    assert report["item_missing_rate"] == 0.5
    assert report["top_items"] == {"치킨": 2}


def test_profile_frame_reports_market_type_counts():
    df = pd.DataFrame({"시장분류코드": ["A", "A", "B"]})
    report = profile_frame(df, source="test")
    assert report["market_type_counts"] == {"A": 2, "B": 1}


def test_profile_frame_skips_optional_sections_when_columns_absent():
    df = pd.DataFrame({"x": [1, 2]})
    report = profile_frame(df, source="test")
    assert "business_no_duplicate_rows" not in report
    assert "item_missing_rows" not in report


def test_build_data_profile_report_combines_sheets_and_tracks_region():
    sheet_a = pd.DataFrame({"취급품목": ["치킨", None]})
    sheet_b = pd.DataFrame({"취급품목": ["빵"]})

    result = build_data_profile_report(
        [("Sheet1", "서울", sheet_a), ("Sheet2", "부산", sheet_b)], input_name="test.xlsx"
    )

    assert len(result["sheets"]) == 2
    assert result["sheets"][0]["sheet_name"] == "Sheet1"
    assert result["sheets"][0]["source_region"] == "서울"
    assert result["sheets"][0]["source"] == "test.xlsx:Sheet1"

    combined = result["combined"]
    assert combined["source"] == "COMBINED"
    assert combined["rows"] == 3
    assert combined["rows_by_region"] == {"서울": 2, "부산": 1}
