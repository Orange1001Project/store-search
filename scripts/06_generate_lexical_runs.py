"""사람 개입 없이, 3개의 서로 다른 lexical(어휘 기반) retrieval 시스템으로 각 쿼리의
top-40 후보를 뽑아 pooling 재료를 만든다.

핵심 로직은 src/store_search_ai/retrieval/lexical.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

사용법:
    python scripts/06_generate_lexical_runs.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_active_queries, load_config
from store_search_ai.retrieval.lexical import (
    build_lexical_run_manifest,
    build_pool_document_texts,
    fit_bm25_scorer,
    fit_char_tfidf_scorer,
    fit_word_tfidf_scorer,
    retrieve_run,
    write_run_files,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    corpus = pd.read_parquet(config["corpus_path"])
    benchmark_dir = Path(config["benchmark_dir"])
    queries = load_active_queries(benchmark_dir)
    run_depth = int(config["pooling"]["run_depth"])

    output_dir = benchmark_dir / "runs" / "pooling"
    output_dir.mkdir(parents=True, exist_ok=True)

    docs = build_pool_document_texts(corpus)

    print("[INFO] fitting char TF-IDF...")
    char_scores = fit_char_tfidf_scorer(docs)
    print("[INFO] fitting word TF-IDF...")
    word_scores = fit_word_tfidf_scorer(docs)
    print("[INFO] fitting BM25 regex-token baseline...")
    bm25_scores = fit_bm25_scorer(docs)

    systems = ["char_tfidf_v1", "word_tfidf_v1", "bm25_regex_v1"]
    score_fns = [char_scores, word_scores, bm25_scores]

    run_stats = []
    for system, score_fn in zip(systems, score_fns):
        run, stats = retrieve_run(system, queries, corpus, score_fn, run_depth)
        write_run_files(run, system, output_dir)
        print()
        print(f"[RUN] {system}")
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        run_stats.append(stats)

    manifest = build_lexical_run_manifest(run_depth, systems, run_stats)
    (output_dir / "lexical_run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("========== LEXICAL POOLING RUNS COMPLETE ==========")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
