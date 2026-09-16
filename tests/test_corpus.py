import pandas as pd
import pytest

from store_search_ai.data.corpus import build_corpus, build_corpus_manifest, text_hash


def _master():
    return pd.DataFrame(
        [
            {
                "store_id": "s1", "store_name": "치킨집", "market_name": "", "market_type": "",
                "item_text": "치킨", "has_item": True, "address": "서울", "latitude": 37.5,
                "longitude": 127.0, "geo_status": "VALID", "legal_dong_code": "1111010100",
                "source_region": "서울특별시", "card_payment": "Y", "mobile_payment": "N",
                "search_text_t1_minimal": "가맹점명: 치킨집 / 취급품목: 치킨",
                "search_text_t2_market": "가맹점명: 치킨집 / 시장명:  / 취급품목: 치킨",
                "search_text_t3_market_type": "가맹점명: 치킨집 / 시장명:  / 시장유형:  / 취급품목: 치킨",
            },
            {
                "store_id": "s2", "store_name": "빵집", "market_name": "", "market_type": "",
                "item_text": None, "has_item": False, "address": "부산", "latitude": 0.0,
                "longitude": 0.0, "geo_status": "MISSING_ZERO", "legal_dong_code": "2100000000",
                "source_region": "부산광역시", "card_payment": "N", "mobile_payment": "N",
                "search_text_t1_minimal": "가맹점명: 빵집 / 취급품목: ",
                "search_text_t2_market": "가맹점명: 빵집 / 시장명:  / 취급품목: ",
                "search_text_t3_market_type": "가맹점명: 빵집 / 시장명:  / 시장유형:  / 취급품목: ",
            },
        ]
    )


def test_text_hash_is_deterministic_and_none_safe():
    assert text_hash("치킨") == text_hash("치킨")
    assert text_hash("치킨") != text_hash("통닭")
    assert text_hash(None) is None
    assert text_hash(float("nan")) is None


def test_build_corpus_rejects_null_store_id():
    df = _master()
    df.loc[0, "store_id"] = None
    with pytest.raises(ValueError, match="NULL"):
        build_corpus(df, dataset_version="v1", corpus_version="c1")


def test_build_corpus_rejects_duplicate_store_id():
    df = pd.concat([_master(), _master().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="중복"):
        build_corpus(df, dataset_version="v1", corpus_version="c1")


def test_build_corpus_adds_doc_id_and_version_columns():
    corpus = build_corpus(_master(), dataset_version="stores_v003", corpus_version="store_corpus_v002")
    assert list(corpus["doc_id"]) == ["s1", "s2"]
    assert (corpus["dataset_version"] == "stores_v003").all()
    assert (corpus["corpus_version"] == "store_corpus_v002").all()
    assert corpus.columns[0] == "doc_id"


def test_build_corpus_computes_content_hashes_per_template():
    corpus = build_corpus(_master(), dataset_version="v1", corpus_version="c1")
    assert corpus.iloc[0]["content_hash_t1"] == text_hash("가맹점명: 치킨집 / 취급품목: 치킨")
    assert corpus.iloc[0]["content_hash_t1"] != corpus.iloc[0]["content_hash_t2"]


def test_build_corpus_manifest_schema():
    corpus = build_corpus(_master(), dataset_version="stores_v003", corpus_version="store_corpus_v002")
    manifest = build_corpus_manifest(
        corpus, dataset_version="stores_v003", corpus_version="store_corpus_v002", source_dataset="input.parquet"
    )
    assert manifest["documents"] == 2
    assert manifest["unique_doc_ids"] == 2
    assert manifest["missing_item_documents"] == 1
    assert manifest["geo_missing_documents"] == 1
    assert manifest["source_dataset"] == "input.parquet"
    assert manifest["templates"]["t1_minimal"] == "가맹점명 + 취급품목"
    assert manifest["primary_template"] is None
