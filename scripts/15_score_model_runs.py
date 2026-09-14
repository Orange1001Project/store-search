"""results/model_eval/*/run_*_<split>.csv 를 한 번에 공식 evaluator로 채점해서 리더보드를 만든다.

zero-shot 모델과 fine-tuned 모델의 run이 섞여 있어도 상관없다 — `14_run_model_eval.py`가
어떤 모델이든 같은 스키마의 run.csv를 만들기 때문에 이 스크립트는 구분하지 않는다.
Colab에서 여러 모델 x 여러 template(t1/t2/t3)로 run을 만들어 오면, 하나씩
`13_evaluate_run.py`를 손으로 돌리는 대신 이 스크립트로 한 번에 비교한다.
채점 로직은 재구현하지 않고 `13_evaluate_run.py`를 서브프로세스로 그대로 호출한다
(docs/MODELING.md의 "왜 이렇게 나눴는가" 원칙과 동일).

사용 예:
    python scripts/15_score_model_runs.py --split val
    python scripts/15_score_model_runs.py --split val --results-dir results/model_eval
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config

RUN_NAME_RE = re.compile(r"^run_(?P<template>.+)_(?P<split>train|val|test)\.csv$")


def find_runs(results_dir: Path, split: str):
    for tag_dir in sorted(results_dir.iterdir()):
        if not tag_dir.is_dir():
            continue
        for run_path in sorted(tag_dir.glob(f"run_*_{split}.csv")):
            match = RUN_NAME_RE.match(run_path.name)
            template = match.group("template") if match else "unknown"
            yield tag_dir.name, template, run_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--results-dir", default="results/model_eval")
    parser.add_argument("--split", choices=["train", "val", "test"], default="val")
    parser.add_argument(
        "--output",
        default=None,
        help="기본값: <results-dir>/leaderboard_<split>.csv",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    qrels_path = benchmark_dir / f"qrels_{args.split}.trec"

    results_dir = Path(args.results_dir)
    runs = list(find_runs(results_dir, args.split))
    if not runs:
        raise SystemExit(
            f"{results_dir} 밑에서 run_*_{args.split}.csv 를 찾지 못했습니다. "
            "Colab에서 만든 run을 이 폴더로 복사했는지 확인하세요."
        )

    evaluate_script = Path(__file__).with_name("13_evaluate_run.py")
    rows = []

    for tag, template, run_path in runs:
        eval_tag = f"{tag}_{template}_{args.split}"
        print(f"[INFO] evaluating {tag}/{template} ...")
        subprocess.run(
            [
                sys.executable, str(evaluate_script),
                "--qrels", str(qrels_path),
                "--run", str(run_path),
                "--tag", eval_tag,
            ],
            check=True,
            capture_output=True,
        )

        eval_json = Path(
            f"artifacts/evaluation/{config['benchmark_version']}/{eval_tag}_evaluation.json"
        )
        report = json.loads(eval_json.read_text(encoding="utf-8"))
        row = {"tag": tag, "template": template}
        row.update(report["aggregate"])
        rows.append(row)

    leaderboard = pd.DataFrame(rows)
    sort_col = "nDCG@10" if "nDCG@10" in leaderboard.columns else leaderboard.columns[-1]
    leaderboard = leaderboard.sort_values(sort_col, ascending=False).reset_index(drop=True)

    output_path = Path(args.output) if args.output else results_dir / f"leaderboard_{args.split}.csv"
    leaderboard.to_csv(output_path, index=False, encoding="utf-8-sig")

    print(f"\n========== MODEL EVAL LEADERBOARD ({args.split}) ==========\n")
    print(leaderboard.to_string(index=False))
    print(f"\n저장: {output_path}")


if __name__ == "__main__":
    main()
