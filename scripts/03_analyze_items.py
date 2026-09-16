"""취급품목(item) 텍스트 품질을 진단하는 리포트 생성 — 파이프라인 진행에 필수는 아니고
taxonomy 정비용 정보성 단계.

핵심 로직은 src/store_search_ai/data/item_analysis.py에 있다. 이 스크립트는 인자 파싱,
파일 저장, 콘솔 출력만 담당한다.

사용법:
    python scripts/03_analyze_items.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.item_analysis import build_item_analysis_report
from store_search_ai.pipeline.common import load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/data/default.yaml")
    parser.add_argument(
        "--input", default=None, help="기본값: data/processed/stores_master_{dataset_version}.parquet"
    )
    parser.add_argument(
        "--output-dir", default=None, help="기본값: artifacts/reports/item_analysis_{dataset_version}"
    )
    args = parser.parse_args()

    dataset_version = load_config(args.config)["dataset_version"]

    if args.input is None:
        args.input = f"data/processed/stores_master_{dataset_version}.parquet"
    if args.output_dir is None:
        args.output_dir = f"artifacts/reports/item_analysis_{dataset_version}"

    input_path = Path(args.input)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(input_path)
    report = build_item_analysis_report(df, dataset_name=input_path.name)

    for table_name, frame in report.items():
        if table_name == "summary" or frame is None:
            continue
        frame.to_csv(output_dir / f"{table_name}_{dataset_version}.csv", index=False, encoding="utf-8-sig")

    summary = report["summary"]
    summary_path = output_dir / f"item_analysis_summary_{dataset_version}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("========== ITEM ANALYSIS V002 COMPLETE ==========")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print("Top 100 item tokens:")
    print()
    print(report["item_token_counts"].head(100).to_string(index=False))


if __name__ == "__main__":
    main()
