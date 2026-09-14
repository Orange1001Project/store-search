from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

from store_search_ai.pipeline.common import load_config, write_trec_qrels


EXPECTED_FILES = {
    "A_train": "annotation_A_train_completed.csv",
    "A_val": "annotation_A_val_completed.csv",
    "A_test": "annotation_A_test_completed.csv",
    "B_val": "annotation_B_val_completed.csv",
    "B_test": "annotation_B_test_completed.csv",
}


def truthy(series: pd.Series) -> pd.Series:
    return (
        series.fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .isin({"Y", "YES", "TRUE", "1"})
    )


def load_completed(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")

    required = {
        "judgment_id", "query_id", "query", "intent_definition",
        "split", "query_family", "query_type", "doc_id",
        "store_name", "item_text", "relevance", "uncertain",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")

    if df["judgment_id"].duplicated().any():
        raise ValueError(f"{path}: duplicate judgment_id")

    if df.duplicated(["query_id", "doc_id"]).any():
        raise ValueError(f"{path}: duplicate query_id/doc_id")

    rel = pd.to_numeric(df["relevance"], errors="coerce")
    invalid = rel.notna() & ~rel.isin([0, 1, 2, 3])
    if invalid.any():
        raise ValueError(
            f"{path}: invalid relevance values "
            f"{df.loc[invalid, 'relevance'].head(10).tolist()}"
        )

    df["relevance"] = rel
    df["uncertain_flag"] = truthy(df["uncertain"])
    return df


def pairwise_report(
    a: pd.DataFrame,
    b: pd.DataFrame,
    split: str,
) -> tuple[pd.DataFrame, dict]:

    if set(a["judgment_id"]) != set(b["judgment_id"]):
        raise ValueError(
            f"{split}: A/B judgment_id sets are not identical."
        )

    merged = a.merge(
        b[["judgment_id", "relevance", "uncertain", "annotator_note"]],
        on="judgment_id",
        how="inner",
        suffixes=("_A", "_B"),
        validate="one_to_one",
    )

    merged["uncertain_A_flag"] = truthy(merged["uncertain_A"])
    merged["uncertain_B_flag"] = truthy(merged["uncertain_B"])

    merged["valid_A"] = (
        merged["relevance_A"].notna()
        & ~merged["uncertain_A_flag"]
    )
    merged["valid_B"] = (
        merged["relevance_B"].notna()
        & ~merged["uncertain_B_flag"]
    )

    valid = merged["valid_A"] & merged["valid_B"]

    merged["exact_agree"] = (
        valid
        & (merged["relevance_A"] == merged["relevance_B"])
    )

    merged["binary_agree"] = (
        valid
        & (
            (merged["relevance_A"] >= 2)
            == (merged["relevance_B"] >= 2)
        )
    )

    # Exact agreement can be auto-finalized.
    merged["final_relevance"] = pd.Series(
        pd.NA,
        index=merged.index,
        dtype="Int64",
    )

    merged.loc[
        merged["exact_agree"],
        "final_relevance",
    ] = (
        merged.loc[
            merged["exact_agree"],
            "relevance_A",
        ].astype("Int64")
    )

    merged["needs_adjudication"] = ~merged["exact_agree"]

    merged["adjudication_priority"] = np.select(
        [
            ~valid,
            valid
            & (
                (merged["relevance_A"] >= 2)
                != (merged["relevance_B"] >= 2)
            ),
            valid
            & (
                merged["relevance_A"]
                != merged["relevance_B"]
            ),
        ],
        [
            "P0_UNCERTAIN_OR_MISSING",
            "P1_BINARY_THRESHOLD",
            "P2_GRADED_ONLY",
        ],
        default="RESOLVED_AGREEMENT",
    )

    v = merged.loc[valid].copy()

    if len(v):
        exact = float(
            (
                v["relevance_A"].astype(int)
                == v["relevance_B"].astype(int)
            ).mean()
        )

        binary = float(
            (
                (v["relevance_A"].astype(int) >= 2)
                == (v["relevance_B"].astype(int) >= 2)
            ).mean()
        )

        kappa = float(
            cohen_kappa_score(
                v["relevance_A"].astype(int),
                v["relevance_B"].astype(int),
            )
        )

        weighted = float(
            cohen_kappa_score(
                v["relevance_A"].astype(int),
                v["relevance_B"].astype(int),
                weights="quadratic",
            )
        )

        binary_kappa = float(
            cohen_kappa_score(
                v["relevance_A"].astype(int) >= 2,
                v["relevance_B"].astype(int) >= 2,
            )
        )
    else:
        exact = binary = kappa = weighted = binary_kappa = None

    report = {
        "split": split,
        "rows": int(len(merged)),
        "valid_both": int(valid.sum()),
        "uncertain_or_missing": int((~valid).sum()),
        "exact_agreement": exact,
        "binary_agreement_rel_ge_2": binary,
        "unweighted_cohen_kappa": kappa,
        "quadratic_weighted_cohen_kappa": weighted,
        "binary_cohen_kappa_rel_ge_2": binary_kappa,
        "needs_adjudication": int(
            merged["needs_adjudication"].sum()
        ),
        "priority_counts": (
            merged.loc[
                merged["needs_adjudication"],
                "adjudication_priority",
            ]
            .value_counts()
            .to_dict()
        ),
    }

    return merged, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/benchmark/storesearch_ko_v1.yaml",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])

    base = (
        benchmark_dir
        / "annotations"
        / "full_annotation_v1"
    )
    completed_dir = base / "completed"
    analysis_dir = base / "analysis"
    qrels_dir = benchmark_dir / "qrels" / "provisional_v1"

    analysis_dir.mkdir(parents=True, exist_ok=True)
    qrels_dir.mkdir(parents=True, exist_ok=True)

    files = {
        key: completed_dir / filename
        for key, filename in EXPECTED_FILES.items()
    }

    missing = [
        str(path)
        for path in files.values()
        if not path.exists()
    ]
    if missing:
        raise FileNotFoundError(
            "Missing completed annotation files:\n"
            + "\n".join(missing)
        )

    data = {
        key: load_completed(path)
        for key, path in files.items()
    }

    # Split integrity.
    expected_split = {
        "A_train": "train",
        "A_val": "val",
        "A_test": "test",
        "B_val": "val",
        "B_test": "test",
    }
    for key, split in expected_split.items():
        found = set(data[key]["split"].astype(str))
        if found != {split}:
            raise ValueError(
                f"{key}: expected split={split}, found={found}"
            )

    # Train: single annotation.
    train = data["A_train"].copy()

    train_usable = train[
        train["relevance"].notna()
        & ~train["uncertain_flag"]
    ].copy()

    train_qrels = train_usable[
        ["query_id", "doc_id", "relevance", "query_family"]
    ].copy()

    train_qrels["relevance"] = (
        train_qrels["relevance"].astype(int)
    )

    train_qrels.to_csv(
        qrels_dir / "qrels_train_provisional.csv",
        index=False,
        encoding="utf-8-sig",
    )

    write_trec_qrels(
        train_qrels,
        qrels_dir / "qrels_train_provisional.trec",
    )

    train[
        train["relevance"].isna()
        | train["uncertain_flag"]
    ].to_csv(
        analysis_dir / "train_uncertain_excluded.csv",
        index=False,
        encoding="utf-8-sig",
    )

    val_merged, val_report = pairwise_report(
        data["A_val"],
        data["B_val"],
        "val",
    )

    test_merged, test_report = pairwise_report(
        data["A_test"],
        data["B_test"],
        "test",
    )

    all_adj = pd.concat(
        [val_merged, test_merged],
        ignore_index=True,
    )

    all_adj["assistant_suggested_relevance"] = ""
    all_adj["assistant_rationale"] = ""
    all_adj["human_adjudication_note"] = ""
    all_adj["exclude_from_gold"] = ""

    visible = [
        "judgment_id",
        "split",
        "query_family",
        "query_type",
        "query_id",
        "query",
        "intent_definition",
        "doc_id",
        "store_name",
        "item_text",
        "market_name",
        "market_type",
        "source_region",
        "relevance_A",
        "relevance_B",
        "uncertain_A",
        "uncertain_B",
        "adjudication_priority",
        "needs_adjudication",
        "final_relevance",
        "assistant_suggested_relevance",
        "assistant_rationale",
        "human_adjudication_note",
        "exclude_from_gold",
    ]

    all_adj[visible].to_csv(
        analysis_dir / "adjudication_val_test_full.csv",
        index=False,
        encoding="utf-8-sig",
    )

    needed = all_adj[
        all_adj["needs_adjudication"]
    ].copy()

    needed[visible].sort_values(
        [
            "adjudication_priority",
            "split",
            "query_family",
            "query_id",
        ]
    ).to_csv(
        analysis_dir / "adjudication_val_test_needed_only.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # Partial agreement qrels are diagnostic only.
    for split, frame in [
        ("val", val_merged),
        ("test", test_merged),
    ]:
        agreed = frame[
            ~frame["needs_adjudication"]
        ][
            [
                "query_id",
                "doc_id",
                "final_relevance",
                "query_family",
            ]
        ].rename(
            columns={"final_relevance": "relevance"}
        )

        agreed.to_csv(
            analysis_dir
            / f"qrels_{split}_agreed_partial_DO_NOT_SCORE.csv",
            index=False,
            encoding="utf-8-sig",
        )

    summary = {
        "benchmark_status": "PROVISIONAL",
        "train": {
            "rows": int(len(train)),
            "queries": int(train["query_id"].nunique()),
            "usable_for_training": int(len(train_usable)),
            "excluded_uncertain": int(
                len(train) - len(train_usable)
            ),
            "grade_distribution": {
                str(int(k)): int(v)
                for k, v in (
                    train_usable["relevance"]
                    .astype(int)
                    .value_counts()
                    .sort_index()
                    .items()
                )
            },
        },
        "val": val_report,
        "test": test_report,
        "total_adjudication_rows": int(len(needed)),
        "total_priority_counts": (
            needed["adjudication_priority"]
            .value_counts()
            .to_dict()
        ),
        "warning": (
            "Do not average A/B labels. "
            "Finalize every needs_adjudication=True row "
            "before scoring Val/Test."
        ),
    }

    (
        analysis_dir
        / "full_annotation_analysis_summary.json"
    ).write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # val+test 전체를 합친 이중 라벨링 커버리지/합치도. calibration(구 08~10, 삭제됨)이 예전에
    # 만들던 것과 같은 스키마로 benchmark_dir 바로 밑에 써서 12_validate_benchmark.py
    # --stage final이 그대로 읽게 한다(그 스크립트는 파일 스키마만 보고 누가 만들었는지는 모른다).
    threshold = int(config["relevance"]["binary_threshold"])
    combined = pd.concat([val_merged, test_merged], ignore_index=True)
    valid_mask = combined["valid_A"] & combined["valid_B"]
    v = combined.loc[valid_mask]
    ar = v["relevance_A"].astype(int)
    br = v["relevance_B"].astype(int)

    agreement_report = {
        "human_double_annotation_required_rows": int(len(combined)),
        "human_double_annotation_completed_rows": int(valid_mask.sum()),
        "double_annotation_coverage": (
            float(valid_mask.sum()) / len(combined) if len(combined) else 1.0
        ),
        "exact_agreement": float((ar.to_numpy() == br.to_numpy()).mean()) if len(ar) else None,
        "binary_agreement_rel_ge_threshold": (
            float(((ar.to_numpy() >= threshold) == (br.to_numpy() >= threshold)).mean())
            if len(ar)
            else None
        ),
        "unweighted_cohen_kappa": float(cohen_kappa_score(ar, br)) if len(ar) else None,
        "quadratic_weighted_cohen_kappa": (
            float(cohen_kappa_score(ar, br, weights="quadratic")) if len(ar) else None
        ),
        "rows_needing_adjudication": int(combined["needs_adjudication"].sum()),
        "binary_relevance_threshold": threshold,
    }

    (benchmark_dir / "agreement_report.json").write_text(
        json.dumps(agreement_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        "========== FULL ANNOTATION PREP COMPLETE =========="
    )
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
