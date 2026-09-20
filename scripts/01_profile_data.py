"""raw xlsx를 아무것도 바꾸지 않고 읽어서 시트별/전체 프로파일링 리포트만 만든다.

핵심 로직은 src/store_search_ai/data/profile.py에 있다. 이 스크립트는 인자 파싱, 파일 IO,
콘솔 출력만 담당한다.

사용법:
    python scripts/01_profile_data.py --input data/raw/stores_20260907.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from store_search_ai.common.io import load_yaml, read_excel_sheets
from store_search_ai.data.profile import build_data_profile_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Excel file path")
    parser.add_argument("--config", default="configs/data/default.yaml")
    parser.add_argument("--output", default="artifacts/reports/data_profile.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="[INFO] %(message)s")

    config = load_yaml(args.config)
    sheet_config = config["excel"]["sheets"]
    sheets = read_excel_sheets(args.input, sheet_config)

    result = build_data_profile_report(sheets, input_name=Path(args.input).name)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print()
    print("========== DATA PROFILE COMPLETE ==========")
    print()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
