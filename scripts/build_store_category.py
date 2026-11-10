"""가게 임시 업종 v0 표를 만든다(src/store_search_ai/data/category.py, configs/category/taxonomy_v0.yaml, docs/archive/SERVICE_PIPELINE_PLAN.md 11-14).

    python scripts/build_store_category.py

출력: data/category/store_category_v0.parquet(doc_id, category, categories, source), .meta.json(업종별 비율, 근거별 비율)
공식 업종 데이터가 오면 같은 열(doc_id, category)로 표를 만들어 바꿔 끼운다.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
import yaml

from store_search_ai.data.category import label_stores, load_taxonomy
from store_search_ai.pipeline.common import sha256_file

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--taxonomy", default="configs/category/taxonomy_v0.yaml")
    parser.add_argument("--corpus", default="data/corpus/store_corpus_v002.parquet")
    parser.add_argument("--out", default="data/category/store_category_v0.parquet")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    taxonomy = load_taxonomy(yaml.safe_load(Path(args.taxonomy).read_text(encoding="utf-8")))
    corpus = pd.read_parquet(args.corpus, columns=["doc_id", "store_name", "item_text"])
    lab = label_stores(corpus, taxonomy)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    lab.to_parquet(out, index=False)
    names = {c.code: c.name for c in taxonomy}
    meta = {"taxonomy": args.taxonomy, "taxonomy_sha256": sha256_file(args.taxonomy), "stores": len(lab),
            "category_share": {names[k]: round(v, 4) for k, v in lab["category"].value_counts(normalize=True).items()},
            "source_share": {k: round(v, 4) for k, v in lab["source"].value_counts(normalize=True).items()},
            "multi_category_share": round(float((lab["categories"].str.count(r"\|") > 0).mean()), 4)}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(json.dumps(meta, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
