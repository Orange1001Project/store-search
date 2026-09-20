"""`results/model_eval/` 밑에 쌓인 여러 모델×템플릿 run을 모아 리더보드로 합치는 로직.

scripts/15_score_model_runs.py의 CLI 배관(인자 파싱, 서브프로세스 호출, 콘솔 출력)을 제외한
핵심 로직 — run 파일 탐색과 리더보드 정렬 (docs/PIPELINE_CODE_REFERENCE.md
`15_score_model_runs.py` 절 참고).
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

RUN_NAME_RE = re.compile(r"^run_(?P<template>.+)_(?P<split>train|val|test)\.csv$")


def find_runs(results_dir: Path, split: str):
    """results_dir/<tag>/run_<template>_<split>.csv 파일을 전부 찾아 (tag, template, path)를 낸다."""

    for tag_dir in sorted(results_dir.iterdir()):
        if not tag_dir.is_dir():
            continue
        for run_path in sorted(tag_dir.glob(f"run_*_{split}.csv")):
            match = RUN_NAME_RE.match(run_path.name)
            template = match.group("template") if match else "unknown"
            yield tag_dir.name, template, run_path


def build_leaderboard(rows: list[dict]) -> pd.DataFrame:
    """{"tag", "template", **aggregate_metrics} 행들을 nDCG@10 기준(없으면 마지막 컬럼)으로
    내림차순 정렬한다.
    """

    leaderboard = pd.DataFrame(rows)
    sort_col = "nDCG@10" if "nDCG@10" in leaderboard.columns else leaderboard.columns[-1]
    return leaderboard.sort_values(sort_col, ascending=False).reset_index(drop=True)
