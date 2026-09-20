"""매장 마스터에서 실제 검색 대상이 될 corpus(document 집합)를 뽑아내는 로직.

scripts/04_build_corpus.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심 로직
전체 — store_id 유일성 검사, corpus 스키마 선택, doc_id/버전 컬럼 부착, template별
content_hash 계산, manifest 조립까지 (docs/PIPELINE_CODE_REFERENCE.md `04_build_corpus.py`
절 참고).
"""

from __future__ import annotations

import hashlib

import pandas as pd

CORPUS_COLUMNS = [
    "store_id", "store_name",
    "market_name", "market_type",
    "item_text", "has_item",
    "address", "latitude", "longitude", "geo_status", "legal_dong_code",
    "source_region",
    "card_payment", "mobile_payment",
    "search_text_t1_minimal", "search_text_t2_market", "search_text_t3_market_type",
]

TEMPLATE_DESCRIPTIONS = {
    "t1_minimal": "가맹점명 + 취급품목",
    "t2_market": "가맹점명 + 시장명 + 취급품목",
    "t3_market_type": "가맹점명 + 시장명 + 시장유형 + 취급품목",
}


def text_hash(value: object) -> str | None:
    """검색 text가 바뀌었는지 추적하기 위한 SHA256. 나중에 incremental embedding에서 사용."""

    if value is None or pd.isna(value):
        return None
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def build_corpus(df: pd.DataFrame, dataset_version: str, corpus_version: str) -> pd.DataFrame:
    """매장 마스터에서 corpus 스키마를 뽑고, doc_id/버전/template별 content_hash를 부착한다.

    store_id가 NULL이거나 중복이면 즉시 에러(코퍼스 문서 ID의 유일성 보장).
    """

    if df["store_id"].isna().any():
        raise ValueError("store_id NULL이 존재합니다.")
    if df["store_id"].duplicated().any():
        raise ValueError("store_id 중복이 존재합니다.")

    corpus = df[CORPUS_COLUMNS].copy()

    # Benchmark / retrieval에서 명칭을 명확히 하기 위해 document ID도 별도로 제공
    corpus.insert(0, "doc_id", corpus["store_id"])

    corpus["dataset_version"] = dataset_version
    corpus["corpus_version"] = corpus_version

    # 각 template별 hash — 향후 text가 안 바뀐 매장은 재임베딩하지 않을 수 있음.
    corpus["content_hash_t1"] = corpus["search_text_t1_minimal"].map(text_hash)
    corpus["content_hash_t2"] = corpus["search_text_t2_market"].map(text_hash)
    corpus["content_hash_t3"] = corpus["search_text_t3_market_type"].map(text_hash)

    return corpus


def build_corpus_manifest(
    corpus: pd.DataFrame,
    dataset_version: str,
    corpus_version: str,
    source_dataset: str,
) -> dict:
    return {
        "corpus_version": corpus_version,
        "dataset_version": dataset_version,
        "source_dataset": source_dataset,
        "documents": len(corpus),
        "unique_doc_ids": int(corpus["doc_id"].nunique()),
        "missing_item_documents": int((~corpus["has_item"]).sum()),
        "geo_missing_documents": int((corpus["geo_status"] != "VALID").sum()),
        "templates": dict(TEMPLATE_DESCRIPTIONS),
        "primary_template": None,
    }
