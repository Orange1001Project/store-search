"""raw xlsx → 정제된 source record → store_id 발급 → 매장 단위 병합(Master)까지 한 번에
수행하는, 파이프라인에서 가장 무거운 전처리 단계.

핵심 로직(시트별 정제, store_id 발급, 매장 단위 병합, summary 조립)은 각각
src/store_search_ai/data/{preprocess,registry,master,search_text}.py에 있다. 이 스크립트는
인자 파싱, 파일 IO 순서 배치, 콘솔 출력만 담당한다.

사용법:
    python scripts/02_preprocess_data.py --input data/raw/stores_20260907.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from store_search_ai.common.io import load_yaml, read_excel_sheets
from store_search_ai.data.master import build_store_master
from store_search_ai.data.preprocess import (
    build_preprocess_summary,
    combine_sheets,
    find_duplicate_candidates,
)
from store_search_ai.data.registry import assign_store_ids
from store_search_ai.data.search_text import attach_templates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Excel file path")
    parser.add_argument("--config", default="configs/data/default.yaml")
    parser.add_argument(
        "--records-output", default=None,
        help="기본값: data/interim/store_records_{dataset_version}.parquet",
    )
    parser.add_argument(
        "--output", default=None,
        help="기본값: data/processed/stores_master_{dataset_version}.parquet",
    )
    parser.add_argument("--registry", default="data/registry/store_registry.parquet")
    parser.add_argument(
        "--report", default=None,
        help="기본값: artifacts/reports/preprocess_summary_{dataset_version}.json",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[INFO] %(message)s")

    config = load_yaml(args.config)
    sheet_config = config["excel"]["sheets"]
    dataset_version = config["dataset_version"]

    if args.records_output is None:
        args.records_output = f"data/interim/store_records_{dataset_version}.parquet"
    if args.output is None:
        args.output = f"data/processed/stores_master_{dataset_version}.parquet"
    if args.report is None:
        args.report = f"artifacts/reports/preprocess_summary_{dataset_version}.json"

    source_file = Path(args.input).name
    sheets = read_excel_sheets(args.input, sheet_config)
    df = combine_sheets(sheets, config, source_file=source_file)

    df, registry = assign_store_ids(df, registry_path=args.registry, dataset_version=dataset_version)
    df = attach_templates(df, config["search_text_templates"])

    duplicates = find_duplicate_candidates(df)

    # 여기에는 중복도 모두 남긴다.
    records_path = Path(args.records_output)
    records_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(records_path, index=False)

    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if not duplicates.empty:
        duplicates.to_parquet(report_path.parent / f"duplicate_candidates_{dataset_version}.parquet", index=False)

    # 여기까지 왔다는 것은 동일 store_id끼리 중요한 정보 충돌이 없다는 뜻은 아니다 —
    # build_store_master()가 충돌을 감지해 결측 처리 + 플래그로 남긴다(에러로 죽이지 않음).
    master, merge_conflicts = build_store_master(df)

    # Store Master에서 item 등이 병합된 뒤 검색용 document를 반드시 다시 생성한다.
    master = attach_templates(master, config["search_text_templates"])

    if not merge_conflicts.empty:
        merge_conflicts.to_csv(
            report_path.parent / f"master_merge_conflicts_{dataset_version}.csv",
            index=False, encoding="utf-8-sig", lineterminator="\n",
        )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    master.to_parquet(output_path, index=False)

    summary = build_preprocess_summary(
        config=config,
        source_file=source_file,
        df=df,
        master=master,
        registry=registry,
        duplicates=duplicates,
        merge_conflicts=merge_conflicts,
    )
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print()
    print("========== PREPROCESS V002 COMPLETE ==========")
    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
