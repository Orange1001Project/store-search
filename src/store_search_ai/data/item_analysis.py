"""취급품목(item) 텍스트 품질을 진단하는 로직.

scripts/03_analyze_items.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심 로직
전체 — 토큰 explode/집계, 결측/충돌/이상치 탐지, long-tail 통계, summary 조립까지
(docs/PIPELINE_CODE_REFERENCE.md `03_analyze_items.py` 절 참고). 파이프라인 진행에 필수는
아니고 taxonomy 정비용 정보성 리포트다.
"""

from __future__ import annotations

import re

import pandas as pd

HTML_ENTITY_RE = re.compile(r"&(?:[A-Za-z]+|#\d+);")
PUNCT_ONLY_RE = re.compile(r"^[^0-9A-Za-z가-힣]+$")

NOISE_TOKEN_LITERALS = {"amp", "-", "."}

# 삭제 대상이 아니라 검토 대상.
LOW_INFORMATION_TERMS = {
    "기타", "서비스", "서비스업", "제품", "판매", "소매", "소매업", "도소매",
    "음식", "음식점", "일반음식점", "식품", "잡화",
}

LONG_ITEM_MIN_LENGTH = 80


def has_unbalanced_parentheses(value: object) -> bool:
    if value is None or pd.isna(value):
        return False

    text = str(value)
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


# ============================================================
# Token tables
# ============================================================

def explode_item_tokens(df: pd.DataFrame) -> pd.DataFrame:
    """매장별 item_tokens 리스트를 토큰 하나당 한 행으로 펼치고, 빈 문자열/NaN을 제거한다."""

    token_df = (
        df[["store_id", "source_region", "item_tokens"]]
        .explode("item_tokens")
        .rename(columns={"item_tokens": "item"})
    )
    token_df["item"] = token_df["item"].astype("string").str.strip()
    return token_df[token_df["item"].notna() & (token_df["item"] != "")]


def build_token_counts(token_df: pd.DataFrame) -> pd.DataFrame:
    return token_df["item"].value_counts().rename_axis("item").reset_index(name="count")


def build_raw_value_counts(df: pd.DataFrame) -> pd.DataFrame:
    return (
        df["item_raw"].dropna().astype("string").str.strip().value_counts()
        .rename_axis("item_raw").reset_index(name="count")
    )


def build_regional_token_counts(token_df: pd.DataFrame) -> pd.DataFrame:
    return (
        token_df.groupby(["source_region", "item"]).size().reset_index(name="count")
        .sort_values(["source_region", "count"], ascending=[True, False])
    )


def noise_token_candidates(token_counts: pd.DataFrame) -> pd.DataFrame:
    noise_mask = token_counts["item"].str.lower().isin(NOISE_TOKEN_LITERALS) | token_counts[
        "item"
    ].str.match(PUNCT_ONLY_RE, na=False)
    return token_counts[noise_mask]


def low_information_tokens(token_counts: pd.DataFrame) -> pd.DataFrame:
    return token_counts[token_counts["item"].isin(LOW_INFORMATION_TERMS)]


def token_coverage(token_counts: pd.DataFrame, n: int, total_token_occurrences: int) -> float:
    if total_token_occurrences == 0:
        return 0.0
    top_sum = int(token_counts.head(n)["count"].sum())
    return top_sum / total_token_occurrences


# ============================================================
# Row-level diagnostics
# ============================================================

def missing_item_stores(df: pd.DataFrame) -> pd.DataFrame:
    return df[~df["has_item"]][
        ["store_id", "store_name", "market_name", "market_type", "address", "source_region"]
    ]


def item_conflict_stores(df: pd.DataFrame) -> pd.DataFrame | None:
    """item_conflict 컬럼이 없으면(구버전 마스터 등) None을 반환한다."""

    if "item_conflict" not in df.columns:
        return None
    return df[df["item_conflict"]][
        ["store_id", "store_name", "item_raw", "item_raw_variants", "item_text", "source_region"]
    ]


def long_item_values(df: pd.DataFrame, min_length: int = LONG_ITEM_MIN_LENGTH) -> pd.DataFrame:
    item_raw_string = df["item_raw"].astype("string")
    item_length = item_raw_string.str.len()

    long_items = df[item_length >= min_length][
        ["store_id", "store_name", "item_raw", "item_text", "source_region"]
    ].copy()
    long_items["item_raw_length"] = item_length[item_length >= min_length]
    return long_items


def unbalanced_parentheses_items(df: pd.DataFrame) -> pd.DataFrame:
    unbalanced_mask = df["item_raw"].map(has_unbalanced_parentheses)
    return df[unbalanced_mask][["store_id", "store_name", "item_raw", "item_text", "source_region"]]


def html_entity_items(df: pd.DataFrame) -> pd.DataFrame:
    item_raw_string = df["item_raw"].astype("string")
    html_mask = item_raw_string.str.contains(HTML_ENTITY_RE, regex=True, na=False)
    return df[html_mask][["store_id", "store_name", "item_raw", "item_text", "source_region"]]


def clean_html_entity_items(df: pd.DataFrame) -> pd.DataFrame:
    clean_item_string = df["item_text"].astype("string")
    clean_html_mask = clean_item_string.str.contains(HTML_ENTITY_RE, regex=True, na=False)
    return df[clean_html_mask][["store_id", "store_name", "item_raw", "item_text", "source_region"]]


# ============================================================
# Report assembly
# ============================================================

def build_item_analysis_report(df: pd.DataFrame, dataset_name: str) -> dict:
    """모든 리포트 테이블 + summary를 한 번에 만든다.

    반환 dict의 테이블 키는 출력 파일명(버전 접미사 제외)과 1:1 대응한다
    (`item_conflict_stores`는 `item_conflict` 컬럼이 없는 마스터에서는 None).
    "summary"는 item_analysis_summary_{dataset_version}.json으로 저장될 dict다.
    """

    token_df = explode_item_tokens(df)
    token_counts = build_token_counts(token_df)
    raw_counts = build_raw_value_counts(df)
    regional_counts = build_regional_token_counts(token_df)

    missing_items = missing_item_stores(df)
    item_conflicts = item_conflict_stores(df)
    long_items = long_item_values(df)
    unbalanced_items = unbalanced_parentheses_items(df)
    html_items = html_entity_items(df)
    clean_html_items = clean_html_entity_items(df)
    noise_tokens = noise_token_candidates(token_counts)
    low_info_tokens = low_information_tokens(token_counts)

    total_token_occurrences = int(token_counts["count"].sum())
    unique_tokens = len(token_counts)
    singleton_tokens = int((token_counts["count"] == 1).sum())

    summary = {
        "dataset": dataset_name,
        "master_store_rows": len(df),
        "item_present_rows": int(df["has_item"].sum()),
        "item_missing_rows": int((~df["has_item"]).sum()),
        "item_missing_rate": float((~df["has_item"]).mean()),
        "unique_raw_item_values": int(df["item_raw"].nunique(dropna=True)),
        "unique_item_text_values": int(df["item_text"].nunique(dropna=True)),
        "unique_tokens": unique_tokens,
        "total_token_occurrences": total_token_occurrences,
        "singleton_tokens": singleton_tokens,
        "singleton_token_rate": singleton_tokens / unique_tokens if unique_tokens else 0.0,
        "tokens_frequency_le_2": int((token_counts["count"] <= 2).sum()),
        "tokens_frequency_le_5": int((token_counts["count"] <= 5).sum()),
        "top_10_token_coverage": token_coverage(token_counts, 10, total_token_occurrences),
        "top_50_token_coverage": token_coverage(token_counts, 50, total_token_occurrences),
        "top_100_token_coverage": token_coverage(token_counts, 100, total_token_occurrences),
        "long_item_rows_ge_80_chars": len(long_items),
        "unbalanced_parentheses_rows": len(unbalanced_items),
        "raw_html_entity_rows": len(html_items),
        "clean_html_entity_rows": len(clean_html_items),
        "noise_token_candidate_count": len(noise_tokens),
        "item_conflict_stores": int(df["item_conflict"].sum()) if "item_conflict" in df.columns else 0,
    }

    return {
        "item_token_counts": token_counts,
        "item_raw_counts": raw_counts,
        "item_token_counts_by_region": regional_counts,
        "missing_item_stores": missing_items,
        "item_conflict_stores": item_conflicts,
        "long_item_values": long_items,
        "unbalanced_parentheses": unbalanced_items,
        "html_entity_items": html_items,
        "clean_html_entity_items": clean_html_items,
        "low_information_tokens": low_info_tokens,
        "summary": summary,
    }
