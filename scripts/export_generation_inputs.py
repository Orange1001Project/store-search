"""A·C 합성 쿼리 LLM 생성(colab/generate_queries.ipynb)의 입력 CSV를 만든다. 계획은 docs/SERVICE_QUERYSET.md 4절.

출력(colab_upload/generation/ → Drive `store-search-ai/generation/`에 올림):
  stores.csv   doc_id, store_name, item_text, market_type — 생성 대상 가맹점(시장유형 비율, 상호명만 있는 가맹점·서비스셋 표본 제외)
  fewshot.csv  bundle(A/C), family, type, query — 프롬프트 예시(기존 벤치마크 train 업종의 활성 쿼리)
  inputs_meta.json

사용법:
    python scripts/export_generation_inputs.py
    python scripts/export_generation_inputs.py --n-stores 200   # 노트북 시험용
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from store_search_ai.data.synthetic_queries import (
    fewshot_examples,
    generation_store_sample,
    template_excluded_doc_ids,
)
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/synthetic_queries_v1.yaml")
    parser.add_argument("--service-config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--families", default="configs/benchmark/query_families_v1.yaml")
    parser.add_argument("--n-stores", type=int, default=None, help="기본: 설정의 llm.n_stores")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    llm_cfg = cfg["llm"]
    bench = load_config(args.benchmark_config)
    families = load_config(args.families)["families"]
    inactive_ids = {r["query_id"] for r in load_config(bench["query_set"]["inactive_queries_path"])["inactive_queries"]}
    generic_items = set(load_config(args.service_config)["item_gap"]["generic_items"])
    corpus = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "market_type"])

    n_stores = args.n_stores or llm_cfg["n_stores"]
    stores = generation_store_sample(
        corpus, n_stores, generic_items, llm_cfg["skip_name_only"],
        template_excluded_doc_ids(cfg["exclude"]["service_template"]), cfg["random_seed"],
    )
    fewshot = fewshot_examples(families, inactive_ids, llm_cfg["fewshot_split"])

    out_dir = Path(llm_cfg["upload_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stores.to_csv(out_dir / "stores.csv", index=False, encoding="utf-8-sig")
    fewshot.to_csv(out_dir / "fewshot.csv", index=False, encoding="utf-8-sig")
    meta = {
        "version": cfg["version"],
        "seed": cfg["random_seed"],
        "n_stores": len(stores),
        "queries_per_store": llm_cfg["queries_per_store"],
        "fewshot_split": llm_cfg["fewshot_split"],
        "fewshot_rows": fewshot["bundle"].value_counts().to_dict(),
        "corpus_path": bench["corpus_path"],
    }
    (out_dir / "inputs_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("가맹점 %d곳, 예시 %s → %s", len(stores), meta["fewshot_rows"], out_dir)
    logger.info("Drive `store-search-ai/generation/`에 세 파일을 올리고 colab/generate_queries.ipynb를 실행하세요.")


if __name__ == "__main__":
    main()
