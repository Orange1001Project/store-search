"""annotation_A_all.csv / annotation_B_val_test.csv를 채운 결과를

`09_prepare_full_annotations.py`가 기대하는 5개 split별 완료 파일로 쪼갠다.

왜 필요한가: `08_make_full_annotation_sheets.py`는 애노테이터가 작업하기 편하도록 A용
`annotation_A_all.csv`(train+val+test 전체 한 파일), B용 `annotation_B_val_test.csv`
(val+test 한 파일)를 만든다. 하지만 `09_prepare_full_annotations.py`는 split별로 분리된
`annotation_A_train_completed.csv`/`annotation_A_val_completed.csv`/`annotation_A_test_completed.csv`/
`annotation_B_val_completed.csv`/`annotation_B_test_completed.csv` 5개를 읽는다(각 split을
독립적으로 검증하기 위함). 이 스크립트가 그 변환을 대신한다 — "split" 컬럼 값으로 행을 나눠서
저장하기만 하므로 애노테이터가 채운 relevance/uncertain 값은 그대로 보존된다.

사용법:
    python scripts/split_completed_annotations.py \
        --a-all path/to/annotation_A_all_completed.csv \
        --b-val-test path/to/annotation_B_val_test_completed.csv

기본값은 둘 다 benchmark_dir/annotations/full_annotation_v1/completed/ 밑에서 찾고, 결과도
같은 폴더에 저장한다 — 즉 그 폴더에 두 파일만 넣고 인자 없이 실행해도 된다.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config


def split_and_save(source_path: Path, splits: list[str], out_dir: Path, prefix: str) -> None:
    df = pd.read_csv(source_path, encoding="utf-8-sig")

    found = set(df["split"].astype(str).unique())
    missing = set(splits) - found
    if missing:
        raise ValueError(f"{source_path}: split {sorted(missing)}에 해당하는 행이 없습니다")

    for split in splits:
        sub = df[df["split"] == split]
        out_path = out_dir / f"{prefix}_{split}_completed.csv"
        sub.to_csv(out_path, index=False, encoding="utf-8-sig")
        print(f"[완료] {out_path} ({len(sub)}행)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--a-all", default=None, help="채운 annotation_A_all_completed.csv 경로")
    parser.add_argument(
        "--b-val-test", default=None, help="채운 annotation_B_val_test_completed.csv 경로"
    )
    args = parser.parse_args()

    config = load_config(args.config)
    completed_dir = (
        Path(config["benchmark_dir"]) / "annotations" / "full_annotation_v1" / "completed"
    )
    completed_dir.mkdir(parents=True, exist_ok=True)

    a_all_path = Path(args.a_all) if args.a_all else completed_dir / "annotation_A_all_completed.csv"
    b_val_test_path = (
        Path(args.b_val_test)
        if args.b_val_test
        else completed_dir / "annotation_B_val_test_completed.csv"
    )

    if not a_all_path.exists():
        raise SystemExit(f"{a_all_path}를 찾을 수 없습니다 (--a-all로 경로 지정 가능)")
    if not b_val_test_path.exists():
        raise SystemExit(f"{b_val_test_path}를 찾을 수 없습니다 (--b-val-test로 경로 지정 가능)")

    split_and_save(a_all_path, ["train", "val", "test"], completed_dir, "annotation_A")
    split_and_save(b_val_test_path, ["val", "test"], completed_dir, "annotation_B")

    print(f"\n[완료] {completed_dir}에 5개 파일 생성. 이어서 실행:")
    print("  python scripts/09_prepare_full_annotations.py")


if __name__ == "__main__":
    main()
