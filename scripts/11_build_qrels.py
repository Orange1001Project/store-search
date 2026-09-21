"""train(provisional) + val/test(adjudication 완료본)를 합쳐 **최종 공식 qrels**를 만든다.

이 단계를 통과해야 비로소 "gold"라고 부를 수 있다. 핵심 로직은
src/store_search_ai/data/qrels_builder.py에 있다 — 이 스크립트는 인자 파싱, 파일 IO 순서
배치, 콘솔 출력만 담당한다.

사용법:
    python scripts/11_build_qrels.py
    python scripts/11_build_qrels.py --round full_annotation_v2
    python scripts/11_build_qrels.py \
        --adjudication benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/adjudication_val_test_full_completed.csv
    python scripts/11_build_qrels.py --freeze   # 산출물을 benchmark_dir/frozen/에 불변 스냅샷으로 복사
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from store_search_ai.data.qrels_builder import (
    assemble_qrels,
    build_manifest,
    build_split_qrels,
    freeze_benchmark,
    load_adjudication,
    load_train_qrels,
    manifest_json,
    save_qrels_outputs,
)
from store_search_ai.pipeline.common import (
    DEFAULT_ANNOTATION_ROUND,
    get_annotation_round_dirs,
    load_config,
    sha256_file,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument(
        "--round",
        default=DEFAULT_ANNOTATION_ROUND,
        help="09/10번과 동일한 --round 값. --adjudication/--train-qrels를 명시하지 않을 때만 쓰인다.",
    )
    parser.add_argument(
        "--adjudication",
        default=None,
        help="기본값: annotations/{round}/analysis/adjudication_val_test_full_completed.csv",
    )
    parser.add_argument(
        "--train-qrels",
        default=None,
        help="기본값: qrels/{round}/qrels_train_provisional.csv",
    )
    parser.add_argument("--freeze", action="store_true")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)
    benchmark_dir = Path(config["benchmark_dir"])
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    annotations_dir, provisional_qrels_dir = get_annotation_round_dirs(benchmark_dir, args.round)

    queries_path = benchmark_dir / "queries.csv"
    queries = pd.read_csv(queries_path, encoding="utf-8-sig")
    active_queries = queries[queries["status"].astype(str).str.lower().eq("active")].copy()
    active_query_ids = set(active_queries["query_id"].astype(str))

    adjudication_path = (
        Path(args.adjudication)
        if args.adjudication
        else annotations_dir / "analysis" / "adjudication_val_test_full_completed.csv"
    )
    adj = load_adjudication(adjudication_path)

    qrels_val = build_split_qrels(adj, "val")
    qrels_test = build_split_qrels(adj, "test")

    train_path = (
        Path(args.train_qrels) if args.train_qrels else provisional_qrels_dir / "qrels_train_provisional.csv"
    )
    qrels_train = load_train_qrels(train_path)

    qrels_frames = assemble_qrels(qrels_train, qrels_val, qrels_test, active_query_ids)

    csv_paths, trec_paths = save_qrels_outputs(benchmark_dir, qrels_frames)

    manifest = build_manifest(
        config=config,
        active_query_count=int(active_queries["query_id"].nunique()),
        qrels_frames=qrels_frames,
        queries_path=queries_path,
        csv_paths=csv_paths,
        trec_paths=trec_paths,
        adjudication_path=adjudication_path,
        train_path=train_path,
        sha256_file=sha256_file,
    )

    manifest_path = benchmark_dir / "benchmark_manifest.json"
    manifest_path.write_text(manifest_json(manifest), encoding="utf-8", newline="\n")

    if args.freeze:
        frozen_dir = benchmark_dir / "frozen"
        files_to_freeze = [
            queries_path,
            benchmark_dir / "annotation_guideline.md",
            csv_paths["train"], csv_paths["val"], csv_paths["test"], csv_paths["all"],
            trec_paths["train"], trec_paths["val"], trec_paths["test"], trec_paths["all"],
            manifest_path,
            config_path,
        ]
        freeze_benchmark(frozen_dir, files_to_freeze)
        print(f"[FROZEN] {frozen_dir}")

    print()
    print("========== FINAL QRELS BUILT ==========")
    print()
    print(manifest_json(manifest))


if __name__ == "__main__":
    main()
