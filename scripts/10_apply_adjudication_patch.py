from __future__ import annotations

import argparse
from pathlib import Path

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


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--full",
        default=(
            "benchmark/storesearch_ko_v1/"
            "annotations/full_annotation_v1/analysis/"
            "adjudication_val_test_full.csv"
        ),
    )

    parser.add_argument(
        "--patch",
        default=(
            "benchmark/storesearch_ko_v1/"
            "annotations/full_annotation_v1/analysis/"
            "adjudication_val_test_needed_only_completed.csv"
        ),
    )

    parser.add_argument(
        "--output",
        default=(
            "benchmark/storesearch_ko_v1/"
            "annotations/full_annotation_v1/analysis/"
            "adjudication_val_test_full_completed.csv"
        ),
    )

    args = parser.parse_args()

    # ==================================================
    # Load
    # ==================================================

    full = pd.read_csv(
        args.full,
        encoding="utf-8-sig",
    )

    patch = pd.read_csv(
        args.patch,
        encoding="utf-8-sig",
    )

    # ==================================================
    # Integrity checks
    # ==================================================

    if patch["judgment_id"].duplicated().any():
        raise ValueError(
            "Patch contains duplicate judgment_id."
        )

    unknown = (
        set(patch["judgment_id"])
        - set(full["judgment_id"])
    )

    if unknown:
        raise ValueError(
            f"Patch contains {len(unknown)} "
            "unknown judgment_ids."
        )

    # ==================================================
    # Validate final_relevance
    # ==================================================

    if "final_relevance" in patch.columns:
        patch["final_relevance"] = pd.to_numeric(
            patch["final_relevance"],
            errors="coerce",
        )

        invalid_relevance = (
            patch["final_relevance"].notna()
            & ~patch["final_relevance"].isin(
                [0, 1, 2, 3]
            )
        )

        if invalid_relevance.any():
            raise ValueError(
                "Patch contains invalid final_relevance. "
                "Allowed values: 0, 1, 2, 3."
            )

    if "assistant_suggested_relevance" in patch.columns:
        patch["assistant_suggested_relevance"] = (
            pd.to_numeric(
                patch["assistant_suggested_relevance"],
                errors="coerce",
            )
        )

    # ==================================================
    # IMPORTANT:
    # Empty CSV columns are often inferred as float64.
    # Cast text patch columns before inserting strings.
    # ==================================================

    for col in STRING_COLUMNS:

        if col not in full.columns:
            full[col] = pd.Series(
                pd.NA,
                index=full.index,
                dtype="string",
            )
        else:
            full[col] = full[col].astype("string")

        if col in patch.columns:
            patch[col] = patch[col].astype("string")

    for col in NUMERIC_COLUMNS:

        if col not in full.columns:
            full[col] = pd.Series(
                pd.NA,
                index=full.index,
                dtype="Float64",
            )
        else:
            full[col] = pd.to_numeric(
                full[col],
                errors="coerce",
            ).astype("Float64")

        if col in patch.columns:
            patch[col] = pd.to_numeric(
                patch[col],
                errors="coerce",
            ).astype("Float64")

    # ==================================================
    # Index by stable judgment_id
    # ==================================================

    patch_idx = patch.set_index(
        "judgment_id"
    )

    full_idx = full.set_index(
        "judgment_id"
    )

    # ==================================================
    # Apply patch
    #
    # Use numpy arrays rather than assigning a Series
    # with a potentially incompatible pandas dtype.
    # ==================================================

    for col in PATCH_COLUMNS:

        if col not in patch_idx.columns:
            continue

        full_idx.loc[
            patch_idx.index,
            col,
        ] = patch_idx[col].to_numpy()

    result = full_idx.reset_index()

    # ==================================================
    # Normalize final relevance
    # ==================================================

    result["final_relevance"] = pd.to_numeric(
        result["final_relevance"],
        errors="coerce",
    ).astype("Int64")

    # ==================================================
    # Save
    # ==================================================

    output = Path(
        args.output
    )

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        output,
        index=False,
        encoding="utf-8-sig",
    )

    # ==================================================
    # Validation
    # ==================================================

    excluded = (
        result["exclude_from_gold"]
        .fillna("")
        .astype(str)
        .str.strip()
        .str.upper()
        .isin(
            [
                "Y",
                "YES",
                "TRUE",
                "1",
            ]
        )
    )

    unresolved = (
        result["final_relevance"].isna()
        & ~excluded
    )

    patched_final = (
        result[
            result["judgment_id"].isin(
                patch["judgment_id"]
            )
        ]["final_relevance"]
        .notna()
        .sum()
    )

    print(
        "========== "
        "ADJUDICATION PATCH APPLIED "
        "=========="
    )

    print(
        f"patch_rows={len(patch)}"
    )

    print(
        f"patch_final_relevance_filled="
        f"{int(patched_final)}"
    )

    print(
        f"output={output}"
    )

    print(
        f"unresolved_non_excluded="
        f"{int(unresolved.sum())}"
    )

    if unresolved.any():

        print()
        print(
            "WARNING: unresolved judgments remain."
        )

        print(
            result.loc[
                unresolved,
                [
                    "judgment_id",
                    "query_id",
                    "store_name",
                    "final_relevance",
                    "exclude_from_gold",
                ],
            ]
            .head(20)
            .to_string(
                index=False
            )
        )

    else:

        print()
        print(
            "SUCCESS: all non-excluded "
            "judgments have final relevance."
        )


if __name__ == "__main__":
    main()