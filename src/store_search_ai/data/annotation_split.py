"""annotation_A_all.csv / annotation_B_val_test.csv를 09_prepare_full_annotations.py가
기대하는 split별 완료 파일로 쪼개는 로직.

scripts/split_completed_annotations.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한
핵심 로직 — "split" 컬럼 값으로 행을 나누기만 하므로 애노테이터가 채운 relevance/uncertain
값은 그대로 보존된다.
"""

from __future__ import annotations

import pandas as pd


def validate_splits_present(df: pd.DataFrame, splits: list[str], source_label: str) -> None:
    found = set(df["split"].astype(str).unique())
    missing = set(splits) - found
    if missing:
        raise ValueError(f"{source_label}: split {sorted(missing)}에 해당하는 행이 없습니다")


def split_by_column(df: pd.DataFrame, column: str, values: list[str]) -> dict[str, pd.DataFrame]:
    return {value: df[df[column] == value] for value in values}
