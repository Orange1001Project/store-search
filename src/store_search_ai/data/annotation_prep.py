"""완료된 애노테이션 시트를 검증하고, train은 provisional qrels로, val/test는 A/B 비교 후
일치분 자동 확정 + 불일치분을 adjudication 대상으로 분리하는 로직.

scripts/09_prepare_full_annotations.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한
핵심 로직 전체 — 완료 시트 로딩/검증, A/B pairwise 비교(합치도/Cohen's kappa 포함), train
qrels 분리, adjudication 테이블 조립, summary/agreement_report 생성까지
(docs/PIPELINE_CODE_REFERENCE.md `09_prepare_full_annotations.py` 절 참고).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

EXPECTED_FILES = {
    "A_train": "annotation_A_train_completed.csv",
    "A_val": "annotation_A_val_completed.csv",
    "A_test": "annotation_A_test_completed.csv",
    "B_val": "annotation_B_val_completed.csv",
    "B_test": "annotation_B_test_completed.csv",
}

EXPECTED_SPLIT_BY_KEY = {
    "A_train": "train",
    "A_val": "val",
    "A_test": "test",
    "B_val": "val",
    "B_test": "test",
}

VISIBLE_ADJUDICATION_COLUMNS = [
    "judgment_id", "split", "query_family", "query_type", "query_id", "query",
    "intent_definition", "doc_id", "store_name", "item_text", "market_name", "market_type",
    "source_region", "relevance_A", "relevance_B", "uncertain_A", "uncertain_B",
    "adjudication_priority", "needs_adjudication", "final_relevance",
    "assistant_suggested_relevance", "assistant_rationale", "human_adjudication_note",
    "exclude_from_gold",
]

REQUIRED_COMPLETED_COLUMNS = {
    "judgment_id", "query_id", "query", "intent_definition",
    "split", "query_family", "query_type", "doc_id",
    "store_name", "item_text", "relevance", "uncertain",
}


def truthy(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.upper().isin({"Y", "YES", "TRUE", "1"})


# ============================================================
# Loading
# ============================================================

def load_completed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")

    missing = REQUIRED_COMPLETED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    if df["judgment_id"].duplicated().any():
        raise ValueError(f"{path}: duplicate judgment_id")
    if df.duplicated(["query_id", "doc_id"]).any():
        raise ValueError(f"{path}: duplicate query_id/doc_id")

    rel = pd.to_numeric(df["relevance"], errors="coerce")
    invalid = rel.notna() & ~rel.isin([0, 1, 2, 3])
    if invalid.any():
        raise ValueError(f"{path}: invalid relevance values {df.loc[invalid, 'relevance'].head(10).tolist()}")

    df["relevance"] = rel
    df["uncertain_flag"] = truthy(df["uncertain"])
    return df


def validate_expected_splits(data: dict[str, pd.DataFrame]) -> None:
    for key, split in EXPECTED_SPLIT_BY_KEY.items():
        found = set(data[key]["split"].astype(str))
        if found != {split}:
            raise ValueError(f"{key}: expected split={split}, found={found}")


# ============================================================
# Train: single annotation
# ============================================================

def split_train_qrels(train: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """train 시트를 (train_qrels, train_usable, train_uncertain_excluded)로 나눈다."""

    train_usable = train[train["relevance"].notna() & ~train["uncertain_flag"]].copy()

    train_qrels = train_usable[["query_id", "doc_id", "relevance", "query_family"]].copy()
    train_qrels["relevance"] = train_qrels["relevance"].astype(int)

    train_uncertain_excluded = train[train["relevance"].isna() | train["uncertain_flag"]]

    return train_qrels, train_usable, train_uncertain_excluded


# ============================================================
# Val/Test: A/B pairwise comparison
# ============================================================

def pairwise_report(a: pd.DataFrame, b: pd.DataFrame, split: str) -> tuple[pd.DataFrame, dict]:
    if set(a["judgment_id"]) != set(b["judgment_id"]):
        raise ValueError(f"{split}: A/B judgment_id sets are not identical.")

    merged = a.merge(
        b[["judgment_id", "relevance", "uncertain", "annotator_note"]],
        on="judgment_id", how="inner", suffixes=("_A", "_B"), validate="one_to_one",
    )

    merged["uncertain_A_flag"] = truthy(merged["uncertain_A"])
    merged["uncertain_B_flag"] = truthy(merged["uncertain_B"])

    merged["valid_A"] = merged["relevance_A"].notna() & ~merged["uncertain_A_flag"]
    merged["valid_B"] = merged["relevance_B"].notna() & ~merged["uncertain_B_flag"]
    valid = merged["valid_A"] & merged["valid_B"]

    merged["exact_agree"] = valid & (merged["relevance_A"] == merged["relevance_B"])
    merged["binary_agree"] = valid & ((merged["relevance_A"] >= 2) == (merged["relevance_B"] >= 2))

    # Exact agreement can be auto-finalized.
    merged["final_relevance"] = pd.Series(pd.NA, index=merged.index, dtype="Int64")
    merged.loc[merged["exact_agree"], "final_relevance"] = (
        merged.loc[merged["exact_agree"], "relevance_A"].astype("Int64")
    )

    merged["needs_adjudication"] = ~merged["exact_agree"]

    merged["adjudication_priority"] = np.select(
        [
            ~valid,
            valid & ((merged["relevance_A"] >= 2) != (merged["relevance_B"] >= 2)),
            valid & (merged["relevance_A"] != merged["relevance_B"]),
        ],
        ["P0_UNCERTAIN_OR_MISSING", "P1_BINARY_THRESHOLD", "P2_GRADED_ONLY"],
        default="RESOLVED_AGREEMENT",
    )

    v = merged.loc[valid].copy()
    if len(v):
        exact = float((v["relevance_A"].astype(int) == v["relevance_B"].astype(int)).mean())
        binary = float(((v["relevance_A"].astype(int) >= 2) == (v["relevance_B"].astype(int) >= 2)).mean())
        kappa = float(cohen_kappa_score(v["relevance_A"].astype(int), v["relevance_B"].astype(int)))
        weighted = float(
            cohen_kappa_score(v["relevance_A"].astype(int), v["relevance_B"].astype(int), weights="quadratic")
        )
        binary_kappa = float(
            cohen_kappa_score(v["relevance_A"].astype(int) >= 2, v["relevance_B"].astype(int) >= 2)
        )
    else:
        exact = binary = kappa = weighted = binary_kappa = None

    report = {
        "split": split,
        "rows": len(merged),
        "valid_both": int(valid.sum()),
        "uncertain_or_missing": int((~valid).sum()),
        "exact_agreement": exact,
        "binary_agreement_rel_ge_2": binary,
        "unweighted_cohen_kappa": kappa,
        "quadratic_weighted_cohen_kappa": weighted,
        "binary_cohen_kappa_rel_ge_2": binary_kappa,
        "needs_adjudication": int(merged["needs_adjudication"].sum()),
        "priority_counts": merged.loc[merged["needs_adjudication"], "adjudication_priority"].value_counts().to_dict(),
    }

    return merged, report


# ============================================================
# Adjudication tables
# ============================================================

def build_adjudication_frame(val_merged: pd.DataFrame, test_merged: pd.DataFrame) -> pd.DataFrame:
    """val+test pairwise 병합 결과를 하나로 합치고, 사람/보조 판정용 빈 컬럼을 추가한다."""

    all_adj = pd.concat([val_merged, test_merged], ignore_index=True)
    all_adj["assistant_suggested_relevance"] = ""
    all_adj["assistant_rationale"] = ""
    all_adj["human_adjudication_note"] = ""
    all_adj["exclude_from_gold"] = ""
    return all_adj[VISIBLE_ADJUDICATION_COLUMNS]


def build_needed_adjudication(all_adj_visible: pd.DataFrame) -> pd.DataFrame:
    needed = all_adj_visible[all_adj_visible["needs_adjudication"]].copy()
    return needed.sort_values(["adjudication_priority", "split", "query_family", "query_id"])


def build_partial_agreement_qrels(frame: pd.DataFrame) -> pd.DataFrame:
    """자동 확정분(불일치 없음)만 모은 진단용 참고 qrels — 채점에 쓰면 안 된다(DO_NOT_SCORE)."""

    agreed = frame[~frame["needs_adjudication"]][["query_id", "doc_id", "final_relevance", "query_family"]]
    return agreed.rename(columns={"final_relevance": "relevance"})


# ============================================================
# Summaries
# ============================================================

def build_full_annotation_summary(
    train: pd.DataFrame,
    train_usable: pd.DataFrame,
    val_report: dict,
    test_report: dict,
    needed: pd.DataFrame,
) -> dict:
    return {
        "benchmark_status": "PROVISIONAL",
        "train": {
            "rows": len(train),
            "queries": int(train["query_id"].nunique()),
            "usable_for_training": len(train_usable),
            "excluded_uncertain": int(len(train) - len(train_usable)),
            "grade_distribution": {
                str(int(k)): int(v)
                for k, v in train_usable["relevance"].astype(int).value_counts().sort_index().items()
            },
        },
        "val": val_report,
        "test": test_report,
        "total_adjudication_rows": len(needed),
        "total_priority_counts": needed["adjudication_priority"].value_counts().to_dict(),
        "warning": (
            "Do not average A/B labels. Finalize every needs_adjudication=True row "
            "before scoring Val/Test."
        ),
    }


def build_agreement_report(val_merged: pd.DataFrame, test_merged: pd.DataFrame, binary_threshold: int) -> dict:
    """val+test 전체를 합친 이중 라벨링 커버리지/합치도.

    calibration(구 08~10, 삭제됨)이 예전에 만들던 것과 같은 스키마 — 12_validate_benchmark.py
    --stage final이 이 스키마를 읽는다(그 스크립트는 파일 스키마만 볼 뿐 누가 만들었는지는
    신경 쓰지 않는다).
    """

    combined = pd.concat([val_merged, test_merged], ignore_index=True)
    valid_mask = combined["valid_A"] & combined["valid_B"]
    v = combined.loc[valid_mask]
    ar = v["relevance_A"].astype(int)
    br = v["relevance_B"].astype(int)

    return {
        "human_double_annotation_required_rows": len(combined),
        "human_double_annotation_completed_rows": int(valid_mask.sum()),
        "double_annotation_coverage": (
            float(valid_mask.sum()) / len(combined) if len(combined) else 1.0
        ),
        "exact_agreement": float((ar.to_numpy() == br.to_numpy()).mean()) if len(ar) else None,
        "binary_agreement_rel_ge_threshold": (
            float(((ar.to_numpy() >= binary_threshold) == (br.to_numpy() >= binary_threshold)).mean())
            if len(ar)
            else None
        ),
        "unweighted_cohen_kappa": float(cohen_kappa_score(ar, br)) if len(ar) else None,
        "quadratic_weighted_cohen_kappa": (
            float(cohen_kappa_score(ar, br, weights="quadratic")) if len(ar) else None
        ),
        "rows_needing_adjudication": int(combined["needs_adjudication"].sum()),
        "binary_relevance_threshold": binary_threshold,
    }
