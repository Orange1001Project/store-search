"""매장 마스터에서 실제 검색 대상이 될 corpus(document 집합)를 뽑아낸다.

핵심 로직은 src/store_search_ai/data/corpus.py에 있다. 이 스크립트는 인자 파싱, 파일 IO,
콘솔 출력만 담당한다.

사용법:
    python scripts/04_build_corpus.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.corpus import build_corpus, build_corpus_manifest
from store_search_ai.pipeline.common import load_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", default="configs/benchmark/storesearch_ko_v1.yaml",
        help="dataset_version/corpus_version을 읽어올 benchmark config",
    )
    parser.add_argument("--input", default=None, help="기본값: data/processed/stores_master_{dataset_version}.parquet")
    parser.add_argument("--output", default=None, help="기본값: data/corpus/{corpus_version}.parquet")
    parser.add_argument("--manifest", default=None, help="기본값: data/corpus/{corpus_version}_manifest.json")
    args = parser.parse_args()

    config = load_config(args.config)
    dataset_version = config["dataset_version"]
    corpus_version = config["corpus_version"]

    if args.input is None:
        args.input = f"data/processed/stores_master_{dataset_version}.parquet"
    if args.output is None:
        args.output = f"data/corpus/{corpus_version}.parquet"
    if args.manifest is None:
        args.manifest = f"data/corpus/{corpus_version}_manifest.json"

    input_path = Path(args.input)
    output_path = Path(args.output)
    manifest_path = Path(args.manifest)

    df = pd.read_parquet(input_path)
    corpus = build_corpus(df, dataset_version=dataset_version, corpus_version=corpus_version)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    corpus.to_parquet(output_path, index=False)

    manifest = build_corpus_manifest(
        corpus, dataset_version=dataset_version, corpus_version=corpus_version, source_dataset=str(input_path)
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    print()
    print("========== CORPUS V001 COMPLETE ==========")
    print()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print()
    print(
        corpus[["doc_id", "search_text_t1_minimal", "search_text_t2_market", "search_text_t3_market_type"]]
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
