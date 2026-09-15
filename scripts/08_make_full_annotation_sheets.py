"""candidate pool 전체를 실제 relevance 판정용 애노테이션 시트로 바꾼다.

train은 애노테이터 A 혼자, val/test는 A/B 독립 이중 판정. 핵심 로직은
src/store_search_ai/data/annotation_sheets.py에 있다 — 이 스크립트는 인자 파싱, 파일 IO,
콘솔 출력만 담당한다.

사용법:
    python scripts/08_make_full_annotation_sheets.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.annotation_sheets import (
    build_annotation_manifest,
    build_annotator_frame,
    build_split_stats,
    prepare_pool,
    write_annotation_file,
)
from store_search_ai.pipeline.common import load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--round", default="full_annotation_v1")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    benchmark_dir = Path(config["benchmark_dir"])

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    queries_path = benchmark_dir / "queries.csv"

    pool = pd.read_csv(pool_path)
    queries = pd.read_csv(queries_path)
    queries = queries[queries["status"] == "active"].copy()

    pool = prepare_pool(pool, queries, args.round)
    seed = int(config["annotation"]["random_seed"])

    output_dir = benchmark_dir / "annotations" / "full_annotation_v1"
    output_dir.mkdir(parents=True, exist_ok=True)

    # ----- Human A: train + val + test 전체 판정 -----
    a = build_annotator_frame(pool, seed, "A")
    write_annotation_file(a, output_dir / "annotation_A_all.csv")
    for split in ["train", "val", "test"]:
        write_annotation_file(a[a["split"] == split], output_dir / f"annotation_A_{split}.csv")

    # ----- Human B: val + test만 독립 재판정 -----
    b = build_annotator_frame(pool, seed, "B", splits=["val", "test"])
    write_annotation_file(b, output_dir / "annotation_B_val_test.csv")
    for split in ["val", "test"]:
        write_annotation_file(b[b["split"] == split], output_dir / f"annotation_B_{split}.csv")

    split_stats = build_split_stats(pool)
    manifest = build_annotation_manifest(args.round, queries, a, b, split_stats)

    manifest_path = output_dir / "annotation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("========== FULL ANNOTATION SHEETS CREATED ==========")
    print()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print()
    print("IMPORTANT:")
    print("- Train: A only")
    print("- Val: A + B independent")
    print("- Test: A + B independent")
    print("- Never use Test for training or hard-negative mining.")


if __name__ == "__main__":
    main()
