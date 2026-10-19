"""B 상호명 합성 학습 쿼리를 규칙으로 만든다(GPU 불필요). 계획은 docs/SERVICE_QUERYSET.md 4절.

가맹점을 뽑아 상호 변형(전체, 지점명 뺀 것, 띄어쓰기 없음, 괄호 안 이름, 브랜드 별칭)을 만들고, 정답은 쿼리 키가 같은
모든 가맹점으로 정한다. 로직은 src/store_search_ai/data/synthetic_queries.py, 설정은 configs/query/synthetic_queries_v1.yaml.

출력(CSV, 한 행 = 쿼리 하나): query, variant, source_doc_id, n_positives, many_positives, positive_doc_ids('|'로 연결)
학습 jsonl(positives/negatives 문서 텍스트)로 바꾸는 건 hard negative·거르기 단계에서 한다.

사용법:
    python scripts/gen_name_queries.py
    python scripts/gen_name_queries.py --n-stores 2000 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from store_search_ai.data.service_queryset import chain_candidates
from store_search_ai.data.synthetic_queries import (
    category_vocab,
    generate_name_queries,
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
    parser.add_argument("--n-stores", type=int, default=None, help="기본: 설정의 names.n_stores")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    service_cfg = load_config(args.service_config)
    bench = load_config(args.benchmark_config)
    corpus = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "source_region"])
    families = load_config(args.families)["families"]
    name_cfg = cfg["names"]
    chain_cfg = service_cfg["chain"]

    chains = chain_candidates(
        corpus, chain_cfg["aliases"], chain_cfg["generic_name_tokens"], chain_cfg["common_name_suffixes"],
        chain_cfg["min_count"],
    )
    brands = sorted(
        set(chains.loc[chains["구분"] == "체인 후보", "브랜드"])
        | {v for vs in chain_cfg["aliases"].values() for v in vs},
        key=len,
        reverse=True,
    )
    vocab = category_vocab(corpus, families, name_cfg["category_min_count"])
    excluded = template_excluded_doc_ids(cfg["exclude"]["service_template"])

    out = generate_name_queries(
        corpus,
        n_stores=args.n_stores or name_cfg["n_stores"],
        brands=brands,
        aliases=chain_cfg["aliases"],
        vocab=vocab,
        exclude_doc_ids=excluded,
        exclude_brands=cfg["exclude"]["exclude_brands"],
        many_positives=name_cfg["many_positives"],
        seed=cfg["random_seed"],
    )
    logger.info("쿼리 %d개 (브랜드 %d개, 업종어 %d개, 제외 가맹점 %d곳)", len(out), len(brands), len(vocab), len(excluded))
    logger.info("변형 종류: %s", out["variant"].value_counts().to_dict())
    logger.info("정답 수: 1개 %d, 2~%d개 %d, 그 이상 %d", (out["n_positives"] == 1).sum(), name_cfg["many_positives"],
                ((out["n_positives"] > 1) & ~out["many_positives"]).sum(), out["many_positives"].sum())
    logger.info("예시:\n%s", out.sample(min(15, len(out)), random_state=0)[["query", "variant", "n_positives"]].to_string())
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return

    out_dir = Path(cfg["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "name_queries.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig")
    meta = {
        "version": cfg["version"],
        "seed": cfg["random_seed"],
        "n_stores": args.n_stores or name_cfg["n_stores"],
        "corpus_path": bench["corpus_path"],
        "excluded_doc_ids": len(excluded),
        "exclude_brands": cfg["exclude"]["exclude_brands"],
        "rows": len(out),
    }
    path.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s", path)


if __name__ == "__main__":
    main()
