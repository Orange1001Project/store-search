"""raw xlsx를 아무것도 바꾸지 않고 읽어서 시트별/전체 프로파일링 리포트를 만드는 로직.

scripts/01_profile_data.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심 로직
전체 (docs/PIPELINE_CODE_REFERENCE.md `01_profile_data.py` 절 참고). 가공은 전혀 하지 않는
순수 진단 단계 — 이후 단계(02~)의 입력이 되지 않는다.
"""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)


def profile_frame(df: pd.DataFrame, source: str) -> dict:
    report = {
        "source": source,
        "rows": len(df),
        "columns": list(df.columns),
        "null_count": {c: int(df[c].isna().sum()) for c in df.columns},
        "null_rate": {c: round(float(df[c].isna().mean()), 6) for c in df.columns},
        "unique_count": {c: int(df[c].nunique(dropna=True)) for c in df.columns},
    }

    if "사업자번호" in df.columns:
        business_no = df["사업자번호"].astype("string").str.replace(r"\D+", "", regex=True)
        report["business_no_duplicate_rows"] = int(business_no.duplicated(keep=False).sum())

    if "가맹점번호" in df.columns:
        merchant_no = df["가맹점번호"].astype("string").str.strip()
        report["merchant_no_missing"] = int((merchant_no.isna() | (merchant_no == "")).sum())

    if "취급품목" in df.columns:
        item = df["취급품목"].astype("string").str.strip()
        missing = item.isna() | (item == "")
        report["item_missing_rows"] = int(missing.sum())
        report["item_missing_rate"] = round(float(missing.mean()), 6)
        report["top_items"] = item[~missing].value_counts().head(50).to_dict()

    if "시장분류코드" in df.columns:
        report["market_type_counts"] = (
            df["시장분류코드"].astype("string").str.strip().value_counts(dropna=False).to_dict()
        )

    return report


def build_data_profile_report(
    sheets: list[tuple[str, str | None, pd.DataFrame]], input_name: str
) -> dict:
    """시트별로 profile_frame()을 돌리고, 전체를 합친 COMBINED 프로파일도 함께 만든다."""

    sheet_reports = []
    combined_frames = []

    for sheet_name, source_region, df in sheets:
        logger.info("Reading sheet=%s, region=%s, rows=%d", sheet_name, source_region, len(df))
        report = profile_frame(df, source=f"{input_name}:{sheet_name}")
        report["sheet_name"] = sheet_name
        report["source_region"] = source_region
        sheet_reports.append(report)

        temp = df.copy()
        temp["__source_sheet"] = sheet_name
        temp["__source_region"] = source_region
        combined_frames.append(temp)

    merged = pd.concat(combined_frames, ignore_index=True)
    combined_profile_input = merged.drop(columns=["__source_sheet", "__source_region"])
    combined_report = profile_frame(combined_profile_input, source="COMBINED")
    combined_report["rows_by_region"] = merged["__source_region"].value_counts().to_dict()

    return {"sheets": sheet_reports, "combined": combined_report}
