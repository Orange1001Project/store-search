from __future__ import annotations

import argparse
import json

from pathlib import Path

import pandas as pd

from store_search_ai.common.io import (
    load_yaml,
    read_excel_sheets,
)

from store_search_ai.data.preprocess import (
    canonicalize,
    find_duplicate_candidates,
)

from store_search_ai.data.search_text import (
    attach_templates,
)

from store_search_ai.data.registry import (
    assign_store_ids,
)

from store_search_ai.data.master import (
    build_store_master,
)


# def check_duplicate_conflicts(
#     df: pd.DataFrame,
# ) -> pd.DataFrame:
#     """
#     같은 store_id가 여러 source row에 있을 때
#     중요한 정보가 서로 다른지 확인한다.

#     같은 매장 중복이어도 item/시장/좌표 등이 다르면
#     자동으로 하나를 버리지 않는다.
#     """

#     duplicate_df = df[
#         df["store_id"]
#         .duplicated(
#             keep=False
#         )
#     ].copy()

#     if duplicate_df.empty:
#         return pd.DataFrame()

#     compare_columns = [
#         "store_name",
#         "business_no",
#         "merchant_no",
#         "address",
#         "latitude",
#         "longitude",
#         "market_type",
#         "market_name",
#         "item_text",
#         "card_payment",
#         "mobile_payment",
#     ]

#     conflicts = []

#     for (
#         store_id,
#         group,
#     ) in duplicate_df.groupby(
#         "store_id"
#     ):

#         conflict_columns = []

#         for column in compare_columns:

#             values = (
#                 group[column]
#                 .dropna()
#                 .astype(str)
#                 .unique()
#             )

#             if len(values) > 1:

#                 conflict_columns.append(
#                     column
#                 )

#         if conflict_columns:

#             conflicts.append(
#                 {
#                     "store_id":
#                         store_id,

#                     "conflict_columns":
#                         ",".join(
#                             conflict_columns
#                         ),

#                     "source_record_keys":
#                         ",".join(
#                             group[
#                                 "source_record_key"
#                             ].astype(str)
#                         ),
#                 }
#             )

#     return pd.DataFrame(
#         conflicts
#     )


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        required=True,
        help="Excel file path",
    )

    parser.add_argument(
        "--config",
        default=(
            "configs/data/"
            "default.yaml"
        ),
    )

    parser.add_argument(
        "--records-output",
        default=None,
        help=(
            "기본값: data/interim/store_records_"
            "{dataset_version}.parquet"
        ),
    )

    parser.add_argument(
        "--output",
        default=None,
        help=(
            "기본값: data/processed/stores_master_"
            "{dataset_version}.parquet"
        ),
    )

    parser.add_argument(
        "--registry",
        default=(
            "data/registry/"
            "store_registry.parquet"
        ),
    )

    parser.add_argument(
        "--report",
        default=None,
        help=(
            "기본값: artifacts/reports/preprocess_summary_"
            "{dataset_version}.json"
        ),
    )

    args = parser.parse_args()

    # --------------------------------------------------
    # Config
    # --------------------------------------------------

    config = load_yaml(
        args.config
    )

    sheet_config = (
        config[
            "excel"
        ][
            "sheets"
        ]
    )

    dataset_version = config["dataset_version"]

    if args.records_output is None:
        args.records_output = (
            f"data/interim/store_records_{dataset_version}.parquet"
        )

    if args.output is None:
        args.output = (
            f"data/processed/stores_master_{dataset_version}.parquet"
        )

    if args.report is None:
        args.report = (
            f"artifacts/reports/preprocess_summary_{dataset_version}.json"
        )

    # --------------------------------------------------
    # Excel 읽기
    # --------------------------------------------------

    sheets = read_excel_sheets(
        args.input,
        sheet_config,
    )

    frames = []

    source_file = (
        Path(
            args.input
        ).name
    )

    # --------------------------------------------------
    # Sheet별 canonicalize
    # --------------------------------------------------

    for (
        sheet_name,
        source_region,
        raw_df,
    ) in sheets:

        print(
            "[INFO] "
            f"preprocessing "
            f"sheet={sheet_name}, "
            f"region={source_region}, "
            f"rows={len(raw_df)}"
        )

        processed = canonicalize(
            raw_df,
            config,
            source_file=source_file,
            source_sheet=sheet_name,
            source_region=source_region,
        )

        frames.append(
            processed
        )

    # --------------------------------------------------
    # 모든 지역 통합
    # --------------------------------------------------

    df = pd.concat(
        frames,
        ignore_index=True,
    )

    # --------------------------------------------------
    # Permanent store_id 할당
    # --------------------------------------------------

    df, registry = assign_store_ids(
        df,
        registry_path=args.registry,
        dataset_version=(
            config[
                "dataset_version"
            ]
        ),
    )

    # --------------------------------------------------
    # Search Text template 생성
    # --------------------------------------------------

    df = attach_templates(
        df,
        config[
            "search_text_templates"
        ],
    )

    # --------------------------------------------------
    # 중복 후보 분석
    # --------------------------------------------------

    duplicates = (
        find_duplicate_candidates(
            df
        )
    )

    # conflicts = (
    #     check_duplicate_conflicts(
    #         df
    #     )
    # )

    # --------------------------------------------------
    # 전체 Source Records 저장
    #
    # 여기에는 중복도 모두 남긴다.
    # --------------------------------------------------

    records_path = Path(
        args.records_output
    )

    records_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    df.to_parquet(
        records_path,
        index=False,
    )

    # --------------------------------------------------
    # Duplicate candidate 저장
    # --------------------------------------------------

    report_path = Path(
        args.report
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not duplicates.empty:

        duplicates.to_parquet(
            report_path.parent
            / f"duplicate_candidates_{dataset_version}.parquet",
            index=False,
        )

    # --------------------------------------------------
    # Conflict 저장
    # --------------------------------------------------

    # if not conflicts.empty:

    #     # 1. 충돌 그룹 요약
    #     conflicts.to_csv(
    #         report_path.parent
    #         / "duplicate_conflicts_v002.csv",
    #         index=False,
    #         encoding="utf-8-sig",
    #     )

    #     # 2. 충돌 store_id에 해당하는 실제 source row 전체 저장
    #     conflict_store_ids = set(
    #         conflicts["store_id"]
    #     )

    #     conflict_rows = (
    #         df[
    #             df["store_id"].isin(
    #                 conflict_store_ids
    #             )
    #         ]
    #         [
    #             [
    #                 "store_id",
    #                 "entity_fingerprint",
    #                 "store_name",
    #                 "business_no",
    #                 "merchant_no",
    #                 "address",
    #                 "latitude",
    #                 "longitude",
    #                 "market_type",
    #                 "market_name",
    #                 "item_raw",
    #                 "item_text",
    #                 "card_payment",
    #                 "mobile_payment",
    #                 "source_region",
    #                 "source_sheet",
    #                 "source_row_no",
    #                 "source_record_key",
    #             ]
    #         ]
    #         .sort_values(
    #             [
    #                 "store_id",
    #                 "source_record_key",
    #             ]
    #         )
    #     )

    #     conflict_rows.to_csv(
    #         report_path.parent
    #         / "duplicate_conflict_rows_v002.csv",
    #         index=False,
    #         encoding="utf-8-sig",
    #     )

    #     raise ValueError(
    #         "동일 store_id 중 중요한 값이 서로 다른 중복 행이 있습니다. "
    #         "artifacts/reports/duplicate_conflict_rows_v002.csv를 확인하세요."
    #     )

    # --------------------------------------------------
    # Store Master 생성
    #
    # 여기까지 왔다는 것은
    # 동일 store_id끼리 중요한 정보 충돌 없음.
    # --------------------------------------------------

    master, merge_conflicts = (
        build_store_master(
            df
        )
    )

    # Store Master에서 item 등이 병합된 뒤
    # 검색용 document를 반드시 다시 생성
    master = attach_templates(
        master,
        config["search_text_templates"],
    )

    if not merge_conflicts.empty:

        merge_conflicts.to_csv(
            report_path.parent
            / f"master_merge_conflicts_{dataset_version}.csv",
            index=False,
            encoding="utf-8-sig",
        )

    output_path = Path(
        args.output
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    master.to_parquet(
        output_path,
        index=False,
    )

    # --------------------------------------------------
    # Summary
    # --------------------------------------------------

    summary = {

        "dataset_version":
            config[
                "dataset_version"
            ],

        "source_record_rows":
            int(
                len(df)
            ),

        "master_store_rows":
            int(
                len(master)
            ),

        "rows_by_region":
            df[
                "source_region"
            ]
            .value_counts()
            .to_dict(),

        "unique_store_ids":
            int(
                master[
                    "store_id"
                ]
                .nunique()
            ),

        "registry_rows":
            int(
                len(registry)
            ),

        "unique_business_nos":
            int(
                df[
                    "business_no"
                ]
                .nunique(
                    dropna=True
                )
            ),

        "missing_merchant_no_rows":
            int(
                df[
                    "merchant_no"
                ]
                .isna()
                .sum()
            ),

        "missing_item_rows":
            int(
                (
                    ~df[
                        "has_item"
                    ]
                )
                .sum()
            ),

        "missing_item_rate":
            float(
                (
                    ~df[
                        "has_item"
                    ]
                )
                .mean()
            ),

        "geo_missing_zero_rows":
            int(
                (
                    df[
                        "geo_status"
                    ]
                    == "MISSING_ZERO"
                )
                .sum()
            ),

        "geo_invalid_rows":
            int(
                (
                    df[
                        "geo_status"
                    ]
                    == "INVALID"
                )
                .sum()
            ),

        "market_type_unmapped_rows":
            int(
                (
                    df[
                        "market_type_status"
                    ]
                    == "UNMAPPED"
                )
                .sum()
            ),

        "duplicate_candidate_rows":
            int(
                len(
                    duplicates
                )
            ),

        "master_merge_conflict_rows":
            int(
                len(
                    merge_conflicts
                )
            ),

        "master_item_conflicts":
            int(
                master[
                    "item_conflict"
                ].sum()
            ),

        "master_merchant_no_conflicts":
            int(
                master[
                    "merchant_no_conflict"
                ].sum()
            ),

        "master_geo_conflicts":
            int(
                master[
                    "geo_conflict"
                ].sum()
            ),

        "master_mobile_payment_conflicts":
            int(
                master[
                    "mobile_payment_conflict"
                ].sum()
            ),

        "source_file":
            source_file,
    }

    report_path.write_text(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------
    # Complete
    # --------------------------------------------------

    print()

    print(
        "========== "
        "PREPROCESS V002 COMPLETE "
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


if __name__ == "__main__":
    main()