"""3rd adjudicator가 채운 "불일치 건 최종 판정"을 전체 val/test 파일에 병합한다.

핵심 로직은 src/store_search_ai/data/adjudication_patch.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

사용법:
    python scripts/10_apply_adjudication_patch.py \
        --patch benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/adjudication_val_test_needed_only_completed.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from store_search_ai.data.adjudication_patch import (
    apply_adjudication_patch,
    build_patch_report,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        default="benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/adjudication_val_test_full.csv",
    )
    parser.add_argument(
        "--patch",
        default=(
            "benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/"
            "adjudication_val_test_needed_only_completed.csv"
        ),
    )
    parser.add_argument(
        "--output",
        default=(
            "benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/"
            "adjudication_val_test_full_completed.csv"
        ),
    )
    args = parser.parse_args()

    full = pd.read_csv(args.full, encoding="utf-8-sig")
    patch = pd.read_csv(args.patch, encoding="utf-8-sig")

    result = apply_adjudication_patch(full, patch)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False, encoding="utf-8-sig")

    report = build_patch_report(result, patch)

    print("========== ADJUDICATION PATCH APPLIED ==========")
    print(f"patch_rows={report['patch_rows']}")
    print(f"patch_final_relevance_filled={report['patch_final_relevance_filled']}")
    print(f"output={output}")
    print(f"unresolved_non_excluded={report['unresolved_non_excluded']}")

    if report["unresolved_non_excluded"]:
        print()
        print("WARNING: unresolved judgments remain.")
        print(report["unresolved_rows"].to_string(index=False))
    else:
        print()
        print("SUCCESS: all non-excluded judgments have final relevance.")


if __name__ == "__main__":
    main()
