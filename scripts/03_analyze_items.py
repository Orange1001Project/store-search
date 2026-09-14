from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config


HTML_ENTITY_RE = re.compile(
    r"&(?:[A-Za-z]+|#\d+);"
)

PUNCT_ONLY_RE = re.compile(
    r"^[^0-9A-Za-z가-힣]+$"
)


def has_unbalanced_parentheses(
    value: object,
) -> bool:

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


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="configs/data/default.yaml",
    )

    parser.add_argument(
        "--input",
        default=None,
        help="기본값: data/processed/stores_master_{dataset_version}.parquet",
    )

    parser.add_argument(
        "--output-dir",
        default=None,
        help="기본값: artifacts/reports/item_analysis_{dataset_version}",
    )

    args = parser.parse_args()

    dataset_version = load_config(args.config)["dataset_version"]

    if args.input is None:
        args.input = f"data/processed/stores_master_{dataset_version}.parquet"

    if args.output_dir is None:
        args.output_dir = f"artifacts/reports/item_analysis_{dataset_version}"

    input_path = Path(
        args.input
    )

    output_dir = Path(
        args.output_dir
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------
    # Master load
    # --------------------------------------------------

    df = pd.read_parquet(
        input_path
    )

    # --------------------------------------------------
    # Token explode
    # --------------------------------------------------

    token_df = (
        df[
            [
                "store_id",
                "source_region",
                "item_tokens",
            ]
        ]
        .explode(
            "item_tokens"
        )
        .rename(
            columns={
                "item_tokens": "item"
            }
        )
    )

    token_df["item"] = (
        token_df["item"]
        .astype("string")
        .str.strip()
    )

    token_df = token_df[
        token_df["item"].notna()
        & (
            token_df["item"]
            != ""
        )
    ]

    # --------------------------------------------------
    # Token count
    # --------------------------------------------------

    token_counts = (
        token_df[
            "item"
        ]
        .value_counts()
        .rename_axis(
            "item"
        )
        .reset_index(
            name="count"
        )
    )

    token_counts.to_csv(
        output_dir
        / f"item_token_counts_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # Raw value count
    # --------------------------------------------------

    raw_counts = (
        df["item_raw"]
        .dropna()
        .astype("string")
        .str.strip()
        .value_counts()
        .rename_axis(
            "item_raw"
        )
        .reset_index(
            name="count"
        )
    )

    raw_counts.to_csv(
        output_dir
        / f"item_raw_counts_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # 지역별 token
    # --------------------------------------------------

    regional_counts = (
        token_df
        .groupby(
            [
                "source_region",
                "item",
            ]
        )
        .size()
        .reset_index(
            name="count"
        )
        .sort_values(
            [
                "source_region",
                "count",
            ],
            ascending=[
                True,
                False,
            ],
        )
    )

    regional_counts.to_csv(
        output_dir
        / f"item_token_counts_by_region_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # Missing item stores
    # --------------------------------------------------

    missing_items = df[
        ~df["has_item"]
    ][
        [
            "store_id",
            "store_name",
            "market_name",
            "market_type",
            "address",
            "source_region",
        ]
    ]

    missing_items.to_csv(
        output_dir
        / f"missing_item_stores_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # Item conflict stores
    # --------------------------------------------------

    if "item_conflict" in df.columns:

        item_conflicts = df[
            df["item_conflict"]
        ][
            [
                "store_id",
                "store_name",
                "item_raw",
                "item_raw_variants",
                "item_text",
                "source_region",
            ]
        ]

        item_conflicts.to_csv(
            output_dir
            / f"item_conflict_stores_{dataset_version}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    # --------------------------------------------------
    # 긴 품목 표현
    # --------------------------------------------------

    item_raw_string = (
        df["item_raw"]
        .astype("string")
    )

    item_length = (
        item_raw_string
        .str.len()
    )

    long_items = df[
        item_length >= 80
    ][
        [
            "store_id",
            "store_name",
            "item_raw",
            "item_text",
            "source_region",
        ]
    ].copy()

    long_items[
        "item_raw_length"
    ] = (
        item_length[
            item_length >= 80
        ]
    )

    long_items.to_csv(
        output_dir
        / f"long_item_values_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # 괄호 이상
    # --------------------------------------------------

    unbalanced_mask = (
        df["item_raw"]
        .map(
            has_unbalanced_parentheses
        )
    )

    unbalanced_items = df[
        unbalanced_mask
    ][
        [
            "store_id",
            "store_name",
            "item_raw",
            "item_text",
            "source_region",
        ]
    ]

    unbalanced_items.to_csv(
        output_dir
        / f"unbalanced_parentheses_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # HTML entity가 원본에 남아 있는 행
    # --------------------------------------------------

    html_mask = (
        item_raw_string
        .str.contains(
            HTML_ENTITY_RE,
            regex=True,
            na=False,
        )
    )

    html_items = df[
        html_mask
    ][
        [
            "store_id",
            "store_name",
            "item_raw",
            "item_text",
            "source_region",
        ]
    ]

    html_items.to_csv(
        output_dir
        / f"html_entity_items_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    clean_item_string = (
    df["item_text"]
    .astype("string")
    )

    clean_html_mask = (
        clean_item_string
        .str.contains(
            HTML_ENTITY_RE,
            regex=True,
            na=False,
        )
    )

    clean_html_items = df[
        clean_html_mask
    ][
        [
            "store_id",
            "store_name",
            "item_raw",
            "item_text",
            "source_region",
        ]
    ]

    clean_html_items.to_csv(
        output_dir
        / f"clean_html_entity_items_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # Token noise 후보
    # --------------------------------------------------

    noise_mask = (
        token_counts["item"]
        .str.lower()
        .isin(
            {
                "amp",
                "-",
                ".",
            }
        )
        |
        token_counts["item"]
        .str.match(
            PUNCT_ONLY_RE,
            na=False,
        )
    )

    noise_tokens = token_counts[noise_mask]

    # --------------------------------------------------
    # Low-information 표현
    #
    # 삭제 대상이 아니라 검토 대상.
    # --------------------------------------------------

    low_information_terms = {
        "기타",
        "서비스",
        "서비스업",
        "제품",
        "판매",
        "소매",
        "소매업",
        "도소매",
        "음식",
        "음식점",
        "일반음식점",
        "식품",
        "잡화",
    }

    low_information_tokens = (
        token_counts[
            token_counts[
                "item"
            ].isin(
                low_information_terms
            )
        ]
    )

    low_information_tokens.to_csv(
        output_dir
        / f"low_information_tokens_{dataset_version}.csv",
        index=False,
        encoding="utf-8-sig",
    )

    # --------------------------------------------------
    # Long-tail statistics
    # --------------------------------------------------

    total_token_occurrences = int(
        token_counts[
            "count"
        ].sum()
    )

    unique_tokens = int(
        len(
            token_counts
        )
    )

    singleton_tokens = int(
        (
            token_counts[
                "count"
            ]
            == 1
        )
        .sum()
    )

    freq_le_2 = int(
        (
            token_counts[
                "count"
            ]
            <= 2
        )
        .sum()
    )

    freq_le_5 = int(
        (
            token_counts[
                "count"
            ]
            <= 5
        )
        .sum()
    )

    def coverage(
        n: int,
    ) -> float:

        if total_token_occurrences == 0:
            return 0.0

        top_sum = int(
            token_counts
            .head(n)[
                "count"
            ]
            .sum()
        )

        return (
            top_sum
            / total_token_occurrences
        )

    # --------------------------------------------------
    # Summary
    # --------------------------------------------------

    summary = {

        "dataset":
            input_path.name,

        "master_store_rows":
            int(
                len(df)
            ),

        "item_present_rows":
            int(
                df[
                    "has_item"
                ].sum()
            ),

        "item_missing_rows":
            int(
                (
                    ~df[
                        "has_item"
                    ]
                )
                .sum()
            ),

        "item_missing_rate":
            float(
                (
                    ~df[
                        "has_item"
                    ]
                )
                .mean()
            ),

        "unique_raw_item_values":
            int(
                df[
                    "item_raw"
                ]
                .nunique(
                    dropna=True
                )
            ),

        "unique_item_text_values":
            int(
                df[
                    "item_text"
                ]
                .nunique(
                    dropna=True
                )
            ),

        "unique_tokens":
            unique_tokens,

        "total_token_occurrences":
            total_token_occurrences,

        "singleton_tokens":
            singleton_tokens,

        "singleton_token_rate":
            (
                singleton_tokens
                / unique_tokens
                if unique_tokens
                else 0.0
            ),

        "tokens_frequency_le_2":
            freq_le_2,

        "tokens_frequency_le_5":
            freq_le_5,

        "top_10_token_coverage":
            coverage(10),

        "top_50_token_coverage":
            coverage(50),

        "top_100_token_coverage":
            coverage(100),

        "long_item_rows_ge_80_chars":
            int(
                len(
                    long_items
                )
            ),

        "unbalanced_parentheses_rows":
            int(
                len(
                    unbalanced_items
                )
            ),

        "raw_html_entity_rows":
            int(
                len(
                    html_items
                )
            ),

        "clean_html_entity_rows":
            int(
                len(
                    clean_html_items
                )
            ),

        "noise_token_candidate_count":
            int(
                len(
                    noise_tokens
                )
            ),

        "item_conflict_stores":
            (
                int(
                    df[
                        "item_conflict"
                    ].sum()
                )
                if "item_conflict"
                in df.columns
                else 0
            ),
    }

    summary_path = (
        output_dir
        / f"item_analysis_summary_{dataset_version}.json"
    )

    summary_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "========== "
        "ITEM ANALYSIS V002 COMPLETE "
        "=========="
    )
    print()

    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()
    print(
        "Top 100 item tokens:"
    )
    print()

    print(
        token_counts
        .head(100)
        .to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()