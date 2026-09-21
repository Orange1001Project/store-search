"""3rd adjudicator가 채운 "불일치 건 최종 판정"을 전체 val/test 파일에 병합한다.

핵심 로직은 src/store_search_ai/data/adjudication_patch.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

--full/--patch/--output을 직접 안 주면 --round(기본 full_annotation_v1)로부터
annotations/{round}/analysis/ 밑 기본 경로를 계산한다.

사용법:
    python scripts/10_apply_adjudication_patch.py
    python scripts/10_apply_adjudication_patch.py --round full_annotation_v2
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
from store_search_ai.pipeline.common import (
    DEFAULT_ANNOTATION_ROUND,
    get_annotation_round_dirs,
    load_config,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument(
        "--round",
        default=DEFAULT_ANNOTATION_ROUND,
        help="09번과 동일한 --round 값. --full/--patch/--output을 명시하지 않을 때만 쓰인다.",
    )
    parser.add_argument("--full", default=None, help="기본값: annotations/{round}/analysis/adjudication_val_test_full.csv")
    parser.add_argument(
        "--patch",
        default=None,
        help="기본값: annotations/{round}/analysis/adjudication_val_test_needed_only_completed.csv",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="기본값: annotations/{round}/analysis/adjudication_val_test_full_completed.csv",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    base, _ = get_annotation_round_dirs(benchmark_dir, args.round)
    analysis_dir = base / "analysis"

    full_path = Path(args.full) if args.full else analysis_dir / "adjudication_val_test_full.csv"
    patch_path = (
        Path(args.patch) if args.patch else analysis_dir / "adjudication_val_test_needed_only_completed.csv"
    )
    output_path = (
        Path(args.output) if args.output else analysis_dir / "adjudication_val_test_full_completed.csv"
    )

    full = pd.read_csv(full_path, encoding="utf-8-sig")
    patch = pd.read_csv(patch_path, encoding="utf-8-sig")

    result = apply_adjudication_patch(full, patch)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_path, index=False, encoding="utf-8-sig", lineterminator="\n")

    report = build_patch_report(result, patch)

    print("========== ADJUDICATION PATCH APPLIED ==========")
    print(f"patch_rows={report['patch_rows']}")
    print(f"patch_final_relevance_filled={report['patch_final_relevance_filled']}")
    print(f"output={output_path}")
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
