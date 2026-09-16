"""lexical run + 규칙 기반 targeted 채널 + 결정적 random negative를 합쳐서 사람이 실제로
라벨링할 후보 pool(candidate_pool_internal.csv)을 만든다. "pooling"의 핵심 단계.

핵심 로직은 src/store_search_ai/data/annotation_pool.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

사용법:
    python scripts/07_build_annotation_pool.py --round lexical_v1
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.annotation_pool import (
    accumulate_random_candidates,
    accumulate_run_candidates,
    accumulate_targeted_candidates,
    build_pool_frame,
    build_pool_stats,
    load_existing_candidates,
    load_pooling_runs,
    merge_pool_history,
    precompute_match_index,
)
from store_search_ai.pipeline.common import load_active_queries, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--round", required=True, help="e.g. lexical_v1 or dense_round1")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    runs_dir = benchmark_dir / "runs" / "pooling"
    corpus = pd.read_parquet(config["corpus_path"])
    queries = load_active_queries(benchmark_dir)

    run_depth = int(config["pooling"]["run_depth"])
    targeted_per_term = int(config["pooling"]["targeted_per_term"])
    random_per_query = int(config["pooling"]["random_per_query"])
    base_seed = int(config["pooling"]["random_seed"])

    run_df = load_pooling_runs(runs_dir, run_depth)

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    candidates = load_existing_candidates(pool_path)

    accumulate_run_candidates(candidates, run_df, args.round)

    item_parts_list, store_name_norm = precompute_match_index(corpus)
    accumulate_targeted_candidates(
        candidates, queries, corpus, item_parts_list, store_name_norm, targeted_per_term, args.round
    )

    accumulate_random_candidates(candidates, queries, corpus, base_seed, random_per_query, args.round)

    pool = build_pool_frame(candidates, queries, corpus, args.round)
    pool.to_csv(pool_path, index=False, encoding="utf-8-sig")

    stats = build_pool_stats(pool, run_df, args.round)
    (benchmark_dir / "pool_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    history_path = benchmark_dir / "pool_history.csv"
    existing_history = pd.read_csv(history_path) if history_path.exists() else None
    merge_pool_history(existing_history, stats, args.round).to_csv(
        history_path, index=False, encoding="utf-8-sig"
    )

    print("========== INTERNAL POOL BUILT ==========")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("NOTE: candidate_pool_internal.csv contains provenance and must not be annotated directly.")


if __name__ == "__main__":
    main()
