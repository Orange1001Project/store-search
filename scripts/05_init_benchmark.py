"""`query_families_v1.yaml`(`import_queryset_xlsx.py`가 생성하는 파일)로부터 `queries.csv`를
생성한다.

핵심 로직은 src/store_search_ai/data/benchmark_init.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

사용법:
    python scripts/05_init_benchmark.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from store_search_ai.data.benchmark_init import (
    GUIDELINE,
    build_queries_frame,
    build_query_manifest,
)
from store_search_ai.pipeline.common import load_config, sha256_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--families", default="configs/benchmark/query_families_v1.yaml")
    args = parser.parse_args()

    config_path = Path(args.config)
    families_path = Path(args.families)
    config = load_config(config_path)
    query_cfg = load_config(families_path)

    benchmark_dir = Path(config["benchmark_dir"])
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    queries = build_queries_frame(query_cfg)

    queries_path = benchmark_dir / "queries.csv"
    queries.to_csv(queries_path, index=False, encoding="utf-8-sig")
    (benchmark_dir / "annotation_guideline.md").write_text(GUIDELINE, encoding="utf-8")

    summary = build_query_manifest(
        config=config,
        query_cfg=query_cfg,
        queries=queries,
        queries_sha256=sha256_file(queries_path),
        families_config_sha256=sha256_file(families_path),
    )
    (benchmark_dir / "query_manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("========== STORESEARCH-KO QUERY SET INITIALIZED ==========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
