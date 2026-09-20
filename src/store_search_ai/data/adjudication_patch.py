"""3rd adjudicator가 채운 "불일치 건 최종 판정"을 전체 val/test 파일에 병합하는 로직.

scripts/10_apply_adjudication_patch.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한
핵심 로직 전체 (docs/PIPELINE_CODE_REFERENCE.md `10_apply_adjudication_patch.py` 절 참고).
judgment_id로 patch를 full에 병합하되, patch에 있는 judgment_id 중 full에 없는 게 있으면
에러(오타/잘못된 파일 방지). "제외되지 않았는데 final_relevance가 여전히 비어있는 행"이
0이어야 다음 단계(11_build_qrels.py)가 성공한다.
"""

from __future__ import annotations

import pandas as pd

PATCH_COLUMNS = [
    "final_relevance",
    "assistant_suggested_relevance",
    "assistant_rationale",
    "human_adjudication_note",
    "exclude_from_gold",
]

STRING_COLUMNS = [
    "assistant_rationale",
    "human_adjudication_note",
    "exclude_from_gold",
]

NUMERIC_COLUMNS = [
    "final_relevance",
    "assistant_suggested_relevance",
]

TRUE_VALUES = {"Y", "YES", "TRUE", "1"}


def validate_patch(full: pd.DataFrame, patch: pd.DataFrame) -> None:
    if patch["judgment_id"].duplicated().any():
        raise ValueError("Patch contains duplicate judgment_id.")

    unknown = set(patch["judgment_id"]) - set(full["judgment_id"])
    if unknown:
        raise ValueError(f"Patch contains {len(unknown)} unknown judgment_ids.")

    if "final_relevance" in patch.columns:
        final_relevance = pd.to_numeric(patch["final_relevance"], errors="coerce")
        invalid_relevance = final_relevance.notna() & ~final_relevance.isin([0, 1, 2, 3])
        if invalid_relevance.any():
            raise ValueError("Patch contains invalid final_relevance. Allowed values: 0, 1, 2, 3.")


def coerce_patch_numeric_columns(patch: pd.DataFrame) -> pd.DataFrame:
    patch = patch.copy()
    if "final_relevance" in patch.columns:
        patch["final_relevance"] = pd.to_numeric(patch["final_relevance"], errors="coerce")
    if "assistant_suggested_relevance" in patch.columns:
        patch["assistant_suggested_relevance"] = pd.to_numeric(
            patch["assistant_suggested_relevance"], errors="coerce"
        )
    return patch


def prepare_dtypes(full: pd.DataFrame, patch: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """빈 CSV 셀이 float64로 잘못 추론되는 문제를 피하려고 patch 컬럼을 명시 캐스팅한다.

    `full`에 patch 컬럼이 아직 없으면(첫 adjudication 라운드) 알맞은 dtype으로 새로 만든다.
    """

    full = full.copy()
    patch = patch.copy()

    for col in STRING_COLUMNS:
        if col not in full.columns:
            full[col] = pd.Series(pd.NA, index=full.index, dtype="string")
        else:
            full[col] = full[col].astype("string")
        if col in patch.columns:
            patch[col] = patch[col].astype("string")

    for col in NUMERIC_COLUMNS:
        if col not in full.columns:
            full[col] = pd.Series(pd.NA, index=full.index, dtype="Float64")
        else:
            full[col] = pd.to_numeric(full[col], errors="coerce").astype("Float64")
        if col in patch.columns:
            patch[col] = pd.to_numeric(patch[col], errors="coerce").astype("Float64")

    return full, patch


def apply_adjudication_patch(full: pd.DataFrame, patch: pd.DataFrame) -> pd.DataFrame:
    """patch를 full에 병합해 최종 adjudication 결과를 반환한다."""

    validate_patch(full, patch)
    patch = coerce_patch_numeric_columns(patch)
    full, patch = prepare_dtypes(full, patch)

    patch_idx = patch.set_index("judgment_id")
    full_idx = full.set_index("judgment_id")

    # Use numpy arrays rather than assigning a Series with a potentially incompatible pandas dtype.
    for col in PATCH_COLUMNS:
        if col not in patch_idx.columns:
            continue
        full_idx.loc[patch_idx.index, col] = patch_idx[col].to_numpy()

    result = full_idx.reset_index()
    result["final_relevance"] = pd.to_numeric(result["final_relevance"], errors="coerce").astype("Int64")
    return result


def build_patch_report(result: pd.DataFrame, patch: pd.DataFrame) -> dict:
    """콘솔 출력/검증용 통계. `unresolved_rows`는 사람이 확인해야 할 미해결 행(최대 20개)."""

    excluded = result["exclude_from_gold"].fillna("").astype(str).str.strip().str.upper().isin(TRUE_VALUES)
    unresolved = result["final_relevance"].isna() & ~excluded

    patched_final = (
        result[result["judgment_id"].isin(patch["judgment_id"])]["final_relevance"].notna().sum()
    )

    return {
        "patch_rows": len(patch),
        "patch_final_relevance_filled": int(patched_final),
        "unresolved_non_excluded": int(unresolved.sum()),
        "unresolved_rows": result.loc[
            unresolved, ["judgment_id", "query_id", "store_name", "final_relevance", "exclude_from_gold"]
        ].head(20),
    }
