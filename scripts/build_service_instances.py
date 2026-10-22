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


def append_new(path: Path, cfg: dict, batch: str) -> None:
    """가져온 활성 쿼리 중 사례가 없는 것만 random 사례로 덧붙인다. 기존 사례(판정했거나 판정 중)는 바꾸지 않는다."""

    inst = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    if "batch" not in inst:
        inst["batch"] = inst["context"].map({"random": "v1", "anchor": "anchor"})
    queries = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    new = queries[(queries["status"] == "active") & ~queries["query_id"].isin(inst["query_id"])]
    rows = new.assign(instance_id=new["query_id"], context="random", anchor_doc_id="", anchor_rule="", batch=batch)
    out = pd.concat([inst, rows[inst.columns.intersection(rows.columns)]], ignore_index=True).fillna("")
    out.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("새 random 사례 %d개(batch=%s) 덧붙임: %s → 전체 %d개", len(rows), batch,
                rows.groupby(["bundle", "split"]).size().to_dict(), len(out))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--append-new", action="store_true",
                        help="이미 있는 instances.csv는 그대로 두고, 아직 사례가 없는 활성 쿼리만 random 사례로 덧붙인다")
    parser.add_argument("--batch", default="extra", help="--append-new로 더한 사례의 batch 이름(pool --set과 같음)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    out = bdir / "instances.csv"
    if out.exists() and args.append_new:
        append_new(out, cfg, args.batch)
        return
    if out.exists():
        raise SystemExit(f"{out}이 이미 있습니다 — anchor 판정을 시작했다면 바꾸면 안 됩니다. 새 쿼리만 더하려면 --append-new, "
                         "정말 다시 만들려면 파일을 지우고 실행하세요.")
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
