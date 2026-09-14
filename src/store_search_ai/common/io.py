from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml


def load_yaml(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def read_excel_sheets(
    path: str | Path,
    sheet_config: dict,
) -> list[tuple[str, str | None, pd.DataFrame]]:
    """
    Excel 파일에서 설정된 시트를 읽는다.

    각 시트 설정에 `source_region`이 있으면 그 고정값을 그대로 쓰고(레거시 다중
    시트 파일 지원), 없으면 `None`을 반환해 호출부(canonicalize)가 주소에서
    행 단위로 지역을 파생하도록 한다.

    Returns
    -------
    [
        (sheet_name, source_region_or_None, dataframe),
        ...
    ]
    """

    path = Path(path)

    if not path.exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    excel_file = pd.ExcelFile(path, engine="openpyxl")

    available_sheets = excel_file.sheet_names

    results = []

    for sheet_name, config in sheet_config.items():

        if sheet_name not in available_sheets:
            raise ValueError(
                f"Sheet '{sheet_name}' not found.\n"
                f"Available sheets: {available_sheets}"
            )

        df = pd.read_excel(
            path,
            sheet_name=sheet_name,
            dtype=str,
            engine="openpyxl",
        )

        source_region = (config or {}).get("source_region")

        results.append(
            (
                sheet_name,
                source_region,
                df,
            )
        )

    return results