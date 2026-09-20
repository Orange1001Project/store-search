from pathlib import Path

import pandas as pd
import pytest
import yaml

from store_search_ai.data.ids import build_entity_fingerprint
from store_search_ai.data.items import parse_item_tokens
from store_search_ai.data.preprocess import build_preprocess_summary, combine_sheets
from store_search_ai.data.text_cleaning import clean_address


def test_address():
    clean,flags=clean_address('대전광역시 중구 예시로 31\xa0\xa0<br>'); assert clean=='대전광역시 중구 예시로 31'; assert flags['address_had_html_break']; assert flags['address_had_nbsp']
def test_items():
    assert parse_item_tokens(None)==[]; assert parse_item_tokens('면류, 건어물')==['면류','건어물']
def test_id_stable():
    assert build_entity_fingerprint('1','가게','주소')==build_entity_fingerprint('1','가게','주소')


REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_config() -> dict:
    return yaml.safe_load((REPO_ROOT / "configs" / "data" / "default.yaml").read_text(encoding="utf-8"))


def _raw_row(store_name: str, address: str) -> dict:
    return {
        "가맹점명": store_name,
        "사업자번호": "1234567890",
        "주소": address,
        "LAT": "37.5",
        "LOT": "127.0",
        "법정동코드": "1111010100",
        "시장분류코드": "기타",
        "시장명": "",
        "취급품목": "치킨",
        "카드결제여부": "Y",
        "모바일결제여부": "N",
    }


def test_combine_sheets_concatenates_canonicalized_sheets_and_derives_region():
    config = _default_config()
    sheet_a = pd.DataFrame([_raw_row("서울가게", "서울특별시 중구 테스트로 1")])
    sheet_b = pd.DataFrame([_raw_row("부산가게", "부산광역시 해운대구 테스트로 2")])

    combined = combine_sheets(
        [("Sheet1", None, sheet_a), ("Sheet2", None, sheet_b)],
        config,
        source_file="test.xlsx",
    )

    assert len(combined) == 2
    assert list(combined["source_sheet"]) == ["Sheet1", "Sheet2"]
    assert list(combined["source_region"]) == ["서울특별시", "부산광역시"]
    assert list(combined.index) == [0, 1]  # ignore_index=True


def test_build_preprocess_summary_schema():
    df = pd.DataFrame(
        {
            "source_region": ["서울특별시", "부산광역시"],
            "business_no": ["1", "2"],
            "merchant_no": ["1", None],
            "has_item": [True, False],
            "geo_status": ["VALID", "MISSING_ZERO"],
            "market_type_status": ["VALID", "UNMAPPED"],
        }
    )
    master = pd.DataFrame(
        {
            "store_id": ["s1", "s2"],
            "item_conflict": [False, True],
            "merchant_no_conflict": [False, False],
            "geo_conflict": [False, False],
            "mobile_payment_conflict": [False, False],
        }
    )
    registry = pd.DataFrame({"store_id": ["s1", "s2", "s3"]})
    duplicates = pd.DataFrame({"store_id": []})
    merge_conflicts = pd.DataFrame({"store_id": ["s2"]})

    summary = build_preprocess_summary(
        config={"dataset_version": "test_v1"},
        source_file="test.xlsx",
        df=df,
        master=master,
        registry=registry,
        duplicates=duplicates,
        merge_conflicts=merge_conflicts,
    )

    assert summary["dataset_version"] == "test_v1"
    assert summary["source_record_rows"] == 2
    assert summary["master_store_rows"] == 2
    assert summary["rows_by_region"] == {"서울특별시": 1, "부산광역시": 1}
    assert summary["missing_merchant_no_rows"] == 1
    assert summary["missing_item_rows"] == 1
    assert summary["missing_item_rate"] == pytest.approx(0.5)
    assert summary["geo_missing_zero_rows"] == 1
    assert summary["market_type_unmapped_rows"] == 1
    assert summary["master_merge_conflict_rows"] == 1
    assert summary["master_item_conflicts"] == 1
    assert summary["source_file"] == "test.xlsx"
