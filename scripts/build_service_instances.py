"""서비스셋 평가 사례(쿼리 × 가정위치)를 만든다 — random(기본 위치) + anchor(정답이 없는 쿼리에 앵커 근처 위치 추가).
규칙과 근거는 src/store_search_ai/data/service_instances.py 머리말.

입력: <benchmark_dir>/queries.csv(판정에 쓴 활성 쿼리), <benchmark_dir>/qrels.csv, 코퍼스
출력: <benchmark_dir>/instances.csv  instance_id, query_id, context(random|anchor), latitude, longitude, anchor_doc_id, …

anchor 사례의 pool은 `build_service_pool.py --set anchor`(나중에 붙인 것은 `--set anchor_extra`)로 만든다(export → Colab → runs → pool).

사용법:
    python scripts/build_service_instances.py                            # 처음 한 번(파일이 있으면 멈춤)
    python scripts/build_service_instances.py --append-new --batch extra_b # 새 활성 쿼리의 random 사례만 덧붙임
    python scripts/build_service_instances.py --add-anchors [--dry-run]   # 판정 뒤 정답 없는 쿼리에 anchor(batch anchor_extra)
    python scripts/build_service_instances.py --add-anchors --proxy-old-qrels --only-batch extra_a --batch anchor_extra_a
        # A head(기존 벤치마크 쿼리): 서비스 판정 전에 기존 판정으로 anchor를 미리 붙여 한 라운드로 판정한다
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


def old_benchmark_qrels(inst: pd.DataFrame, bench: dict) -> pd.DataFrame:
    """기존 벤치마크에서 가져온 쿼리(같은 문자열)의 기존 판정을 서비스 query_id로 옮긴다 — 판정 전 anchor 판단용 대용 qrels.

    기존 판정은 전국 pool의 일부만 판정한 것이라 '1km 안 정답 있음'은 확실하지만 '없음'은 과대 추정이다. 그래서 anchor가 필요
    이상으로 붙을 수는 있어도(주 평가셋은 random을 먼저 쓰므로 무해) 빠지지는 않는다. 서비스 판정 뒤 --add-anchors로 다시 확인한다.
    """

    from store_search_ai.data.service_import import normalize

    bdir = Path(bench["benchmark_dir"])
    oq = pd.read_csv(bdir / "queries.csv", encoding="utf-8-sig")[["query_id", "query"]]
    oqr = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")[["query_id", "doc_id", "relevance"]]
    oqr = oqr.merge(oq.rename(columns={"query_id": "old_id"}), left_on="query_id", right_on="old_id")
    oqr["key"] = oqr["query"].map(normalize)
    keys = inst[["query_id", "query"]].drop_duplicates("query_id").assign(key=lambda f: f["query"].map(normalize))
    return keys[["query_id", "key"]].merge(oqr[["key", "doc_id", "relevance"]], on="key")[["query_id", "doc_id", "relevance"]]


def add_anchors(path: Path, cfg: dict, bench: dict, batch: str, dry_run: bool, proxy_old: bool = False,
                only_batch: str | None = None) -> None:
    """anchor가 없는 활성 쿼리 중 기본 위치 1km 안에 정답이 없는 것에 anchor 사례를 덧붙인다(처음 만들 때와 같은 규칙).

    --append-new로 나중에 더한 쿼리는 random 사례만 있어, 판정 뒤 정답이 없으면 주 평가셋 후보가 될 수 없었다
    (2026-10-26 점검 4번: 추가 C 15개). 판정이 끝난 쿼리에만 쓴다 — 정답 유무를 qrels로 보기 때문이다.
    """

    inst = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    qrels = old_benchmark_qrels(inst, bench) if proxy_old else pd.read_csv(path.parent / "qrels.csv", encoding="utf-8-sig")
    corpus = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "latitude", "longitude",
                                                            "geo_status"])
    corpus = corpus[corpus["geo_status"] == "VALID"]
    has_anchor = set(inst.loc[inst["context"] == "anchor", "query_id"])
    judged = set(qrels["query_id"])
    base = inst[(inst["context"] == "random") & ~inst["query_id"].isin(has_anchor) & inst["query_id"].isin(judged)]
    if only_batch:
        base = base[base["batch"] == only_batch]
    keywords = dict(cfg["judging"].get("anchor_keywords") or {})
    oa = cfg["import"].get("old_benchmark_a")
    if oa and Path(oa["path"]).exists():   # A head(기존 벤치마크 쿼리)의 앵커 단어 — select_old_benchmark_a.py가 정함
        oa_rows = pd.read_csv(oa["path"], encoding="utf-8-sig", keep_default_na=False)
        keywords.update(dict(zip(oa_rows["query"], oa_rows["anchor_keyword"], strict=True)))
    built = build_instances(base.drop(columns=["instance_id", "context", "anchor_doc_id", "anchor_rule", "batch"]), qrels,
                            corpus, cfg["chain"]["aliases"], radius_km=min(cfg["judging"]["report_radii_km"]),
                            anchor_keywords=keywords)
    rows = built[built["context"] == "anchor"].assign(batch=batch)
    logger.info("anchor 없는 판정 완료 쿼리 %d개 → 새 anchor 사례 %d개(batch=%s): %s", len(base), len(rows), batch,
                rows.groupby(["bundle", "split"]).size().to_dict())
    if len(rows):
        logger.info("  %s", ", ".join(f"{q}({b})" for q, b in zip(rows["query"], rows["batch"], strict=True)))
    if dry_run or rows.empty:
        return
    out = pd.concat([inst, rows[inst.columns.intersection(rows.columns)]], ignore_index=True).fillna("")
    out.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s (전체 %d개)", path, len(out))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--append-new", action="store_true",
                        help="이미 있는 instances.csv는 그대로 두고, 아직 사례가 없는 활성 쿼리만 random 사례로 덧붙인다")
    parser.add_argument("--add-anchors", action="store_true",
                        help="anchor가 없는 판정 완료 쿼리 중 1km 안 정답이 없는 것에 anchor 사례를 덧붙인다(batch 기본 anchor_extra)")
    parser.add_argument("--batch", default=None, help="덧붙인 사례의 batch 이름(pool --set과 같음). 기본 extra / anchor_extra")
    parser.add_argument("--dry-run", action="store_true", help="--add-anchors: 저장하지 않고 개수만")
    parser.add_argument("--proxy-old-qrels", action="store_true",
                        help="--add-anchors: 서비스 판정 전, 기존 벤치마크 판정(같은 문자열)으로 1km 안 정답 유무를 본다(A head)")
    parser.add_argument("--only-batch", default=None, help="--add-anchors: 이 batch의 random 사례에만 anchor를 붙인다")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    out = bdir / "instances.csv"
    if out.exists() and args.add_anchors:
        add_anchors(out, cfg, bench, args.batch or "anchor_extra", args.dry_run, args.proxy_old_qrels, args.only_batch)
        return
    if out.exists() and args.append_new:
        append_new(out, cfg, args.batch or "extra")
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
