"""서비스셋 평가 사례(쿼리 × 가정위치)를 만든다 — random(기본 위치) + anchor(정답이 없는 쿼리에 앵커 근처 위치 추가).
규칙과 근거는 src/store_search_ai/data/service_instances.py 머리말.

입력: <benchmark_dir>/queries.csv(판정에 쓴 활성 쿼리), <benchmark_dir>/qrels.csv, 코퍼스
출력: <benchmark_dir>/instances.csv  instance_id, query_id, context(random|anchor), latitude, longitude, anchor_doc_id, …

anchor 사례의 pool은 `build_service_pool.py --set anchor`로 만든다(export → Colab → runs → pool).

사용법:
    python scripts/build_service_instances.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from store_search_ai.data.service_instances import answerable_counts, build_instances
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    out = bdir / "instances.csv"
    if out.exists():
        raise SystemExit(f"{out}이 이미 있습니다 — anchor 판정을 시작했다면 바꾸면 안 됩니다. 정말 다시 만들려면 파일을 지우고 실행하세요.")
    queries = pd.read_csv(bdir / "queries.csv", encoding="utf-8-sig", keep_default_na=False)
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    corpus = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "latitude", "longitude",
                                                            "geo_status"])
    corpus = corpus[corpus["geo_status"] == "VALID"]

    radius = min(cfg["judging"]["report_radii_km"])
    instances = build_instances(queries, qrels, corpus, cfg["chain"]["aliases"], radius_km=radius,
                                anchor_keywords=cfg["judging"].get("anchor_keywords"))
    anchors = instances[instances["context"] == "anchor"]
    random = instances[instances["context"] == "random"]
    counts = answerable_counts(random, qrels, corpus, radius)
    eligible = random[random["bundle"].isin(["A", "B", "C"]) & (random["instance_id"].map(counts) == 0)
                      & ~((random["bundle"] == "B") & (random["location_source"] == "store"))]
    missing = eligible[~eligible["query_id"].isin(anchors["query_id"])]
    logger.info("%skm 안 정답이 없는 A·B(브랜드)·C 쿼리 %d개 → anchor 사례 %d개: %s", radius, len(eligible), len(anchors),
                anchors.groupby(["bundle", "split"]).size().to_dict())
    if len(missing):
        logger.info("전국에 앵커 후보 가게가 없어 못 붙인 쿼리 %d개: %s", len(missing), ", ".join(missing["query"]))
    instances.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s (random %d + anchor %d)", out, len(random), len(anchors))


if __name__ == "__main__":
    main()
