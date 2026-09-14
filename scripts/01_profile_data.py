from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.common.io import (
    load_yaml,
    read_excel_sheets,
)
from store_search_ai.data.profile import profile_frame


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--input",
        required=True,
        help="Excel file path",
    )

    parser.add_argument(
        "--config",
        default="configs/data/default.yaml",
    )

    parser.add_argument(
        "--output",
        default="artifacts/reports/data_profile.json",
    )

    args = parser.parse_args()

    config = load_yaml(args.config)

    sheet_config = config["excel"]["sheets"]

    sheets = read_excel_sheets(
        args.input,
        sheet_config,
    )

    sheet_reports = []

    combined_frames = []

    for sheet_name, source_region, df in sheets:

        print(
            f"[INFO] Reading sheet={sheet_name}, "
            f"region={source_region}, rows={len(df)}"
        )

        report = profile_frame(
            df,
            source=f"{Path(args.input).name}:{sheet_name}",
        )

        report["sheet_name"] = sheet_name
        report["source_region"] = source_region

        sheet_reports.append(report)

        temp = df.copy()

        temp["__source_sheet"] = sheet_name
        temp["__source_region"] = source_region

        combined_frames.append(temp)

    merged = pd.concat(
        combined_frames,
        ignore_index=True,
    )

    combined_profile_input = merged.drop(
        columns=[
            "__source_sheet",
            "__source_region",
        ],
    )

    combined_report = profile_frame(
        combined_profile_input,
        source="COMBINED",
    )

    combined_report["rows_by_region"] = (
        merged["__source_region"]
        .value_counts()
        .to_dict()
    )

    result = {
        "sheets": sheet_reports,
        "combined": combined_report,
    }

    output_path = Path(args.output)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("========== DATA PROFILE COMPLETE ==========")
    print()

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()