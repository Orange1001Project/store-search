"""지금까지 나온 산출물 전체(쿼리/pool/qrels)의 무결성을 점검하는 게이트.

`pilot`은 구조적 검증만, `final`은 config가 정한 최소 기준까지 검사한다. 핵심 로직은
src/store_search_ai/data/benchmark_validation.py에 있다. 이 스크립트는 인자 파싱, 파일 IO,
콘솔 출력만 담당한다.

사용법:
    python scripts/12_validate_benchmark.py --stage pilot
    python scripts/12_validate_benchmark.py --stage final
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.benchmark_validation import build_validation_report
from store_search_ai.pipeline.common import load_active_queries, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--stage", choices=["pilot", "final"], default="pilot")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    queries = load_active_queries(benchmark_dir)
    corpus = pd.read_parquet(config["corpus_path"])

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    pool = pd.read_csv(pool_path) if pool_path.exists() else None

    qrels_path = benchmark_dir / "qrels.csv"
    qrels = pd.read_csv(qrels_path) if qrels_path.exists() else None

    agreement_path = benchmark_dir / "agreement_report.json"
    agreement = (
        json.loads(agreement_path.read_text(encoding="utf-8")) if agreement_path.exists() else None
    )

    report = build_validation_report(
        config, args.stage, queries, corpus, pool=pool, qrels=qrels, agreement=agreement
    )

    (benchmark_dir / f"validation_{args.stage}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    print("========== BENCHMARK VALIDATION ==========")
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
