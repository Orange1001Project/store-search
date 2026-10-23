"""서비스셋으로 검색 파이프라인 구성을 비교한다(docs/SERVICE_PIPELINE_PLAN.md). 기본은 dev만 채점한다 — test는 단계가 끝날 때
`--split test`로 고른 구성 하나만(`--only`).

실험(--exp)
  hybrid   v1 + char BM25: RRF(k=10·30·60), min-max 가중합(v1 가중치 α=0.1~0.9). 기준 = v1 단독, BM25 단독
  hybrid2  상호 일치 가산점(name match boost): v1+이름, 가중합+이름

출력: results/service_pipeline/<exp>_<split>.csv — 구성 × 반경 × 묶음별 nDCG@10, nDCG@10(판정만), Judged@10, bad@3, top1_ok

사용법:
    python scripts/eval_service_pipeline.py --exp hybrid
    python scripts/eval_service_pipeline.py --exp hybrid --split test --only "convex a=0.7"
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.evaluation.service_eval import instance_qrels, score_system
from store_search_ai.pipeline.common import load_config
from store_search_ai.retrieval.fusion import boost, convex, name_match, rrf

logger = logging.getLogger(__name__)
V1 = "bge_m3_ft_mj_20261014_0743"


def load_runs(bdir: Path) -> dict[str, pd.DataFrame]:
    runs: dict[str, list[pd.DataFrame]] = {}
    for d in ("runs", "runs_anchor", "runs_extra"):
        for path in sorted((bdir / d).glob("*.csv")):
            runs.setdefault(path.stem, []).append(pd.read_csv(path, encoding="utf-8-sig"))
    return {k: pd.concat(v, ignore_index=True) for k, v in runs.items()}


def hybrid_variants(runs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    v1, bm25 = runs[V1], runs["char_bm25"]
    out = {"v1": v1, "bm25": bm25}
    for k in (10, 30, 60):
        out[f"rrf k={k}"] = rrf([v1, bm25], k=k)
    for a in np.round(np.arange(0.1, 1.0, 0.1), 1):
        out[f"convex a={a}"] = convex([v1, bm25], [a, 1 - a])
    return out


def name_hits(run: pd.DataFrame, instances: pd.DataFrame, names: pd.Series) -> pd.Series:
    q = instances.set_index("instance_id")
    core = {}
    for i in q.index:
        t = q.at[i, "query"]
        for w in str(q.at[i, "region_text"]).split():
            t = t.replace(w, "")
        core[i] = t
    return pd.Series([name_match(core.get(i, ""), names.get(d, "")) for i, d in zip(run["query_id"], run["doc_id"], strict=True)],
                     index=run.index)


def hybrid2_variants(runs: dict[str, pd.DataFrame], instances: pd.DataFrame, names: pd.Series) -> dict[str, pd.DataFrame]:
    """상호 일치 가산점: v1에만 / 가중합에. 상호명 쿼리는 끌어올리고 업종·상황 쿼리는 v1 순위를 거의 그대로 둔다."""

    v1 = runs[V1][runs[V1]["query_id"].isin(instances["instance_id"])]
    bm25 = runs["char_bm25"][runs["char_bm25"]["query_id"].isin(instances["instance_id"])]
    out = {"v1": v1, "convex a=0.7": convex([v1, bm25], [0.7, 0.3])}
    # 상호 일치는 v1과 BM25 후보를 합친 목록에서 본다(BM25만 찾은 상호도 올릴 수 있게)
    union = convex([v1, bm25], [1.0, 0.0], name="union_v1")      # BM25 후보도 포함, 점수는 v1만
    hu = name_hits(union, instances, names)
    for beta in (0.3, 0.5, 1.0):
        out[f"v1+name b={beta}"] = boost(union, hu, beta, f"v1+name b={beta}")
    for a in (0.7, 0.8, 0.9):
        c = convex([v1, bm25], [a, 1 - a])
        hc = name_hits(c, instances, names)
        for beta in (0.5, 1.0):
            out[f"convex a={a}+name b={beta}"] = boost(c, hc, beta, f"convex a={a}+name b={beta}")
    return out


def condense(run: pd.DataFrame, instances: pd.DataFrame, qrels: pd.DataFrame) -> pd.DataFrame:
    """판정된 (쿼리, 가맹점)만 남긴 run(Sakai 2007 condensed list). 판정 누락이 있는 새 구성을 공정하게 비교하려고 같이 본다."""

    base = instances.set_index("instance_id")["query_id"]
    judged = set(zip(qrels["query_id"], qrels["doc_id"], strict=True))
    keep = [(base.get(i), d) in judged for i, d in zip(run["query_id"], run["doc_id"], strict=True)]
    return run[keep]


def summarize(per: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for keys, g in per.groupby(["config", "radius_km"]):
        rows.append({"config": keys[0], "radius_km": keys[1], "bundle": "전체", **_agg(g)})
        for b, gb in g.groupby("bundle"):
            rows.append({"config": keys[0], "radius_km": keys[1], "bundle": b, **_agg(gb)})
    return pd.DataFrame(rows)


def _agg(g: pd.DataFrame) -> dict:
    return {"instances": len(g), "nDCG@10": g["nDCG@10"].mean(), "nDCG@10_condensed": g["nDCG@10_condensed"].mean(),
            "Judged@10": g["Judged@10"].mean(), "bad@3": g["bad@3"].mean(), "top1_ok": g["top1_ok"].mean()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exp", choices=["hybrid", "hybrid2"], required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--only", action="append", help="채점할 구성 이름(여러 번). test는 반드시 지정")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.split == "test" and not args.only:
        raise SystemExit("test는 고른 구성만 채점합니다 — --only로 지정하세요(docs/SERVICE_PIPELINE_PLAN.md 3절).")

    cfg = load_config(args.config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    bench = load_config(args.benchmark_config)
    instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    instances = instances[instances["split"] == args.split]
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]
    iq = instance_qrels(instances, qrels, coords)

    runs = load_runs(bdir)
    if args.exp == "hybrid":
        variants = hybrid_variants(runs)
    else:
        names = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name"]).set_index("doc_id")["store_name"]
        variants = hybrid2_variants(runs, instances, names)
    if args.only:
        variants = {k: v for k, v in variants.items() if k in set(args.only) | {"v1"}}
    per = []
    for name, run in variants.items():
        run = run[run["query_id"].isin(instances["instance_id"])]
        for radius in cfg["judging"]["report_radii_km"]:
            s = score_system(run, iq, instances, coords, radius)
            c = score_system(condense(run, instances, qrels), iq, instances, coords, radius)
            s = s.merge(c[["instance_id", "nDCG@10"]].rename(columns={"nDCG@10": "nDCG@10_condensed"}), on="instance_id")
            per.append(s.assign(config=name, radius_km=radius))
    per = pd.concat(per, ignore_index=True).merge(instances[["instance_id", "bundle"]], on="instance_id")
    summary = summarize(per)
    out = Path("results/service_pipeline")
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / f"{args.exp}_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    per.to_csv(out / f"{args.exp}_{args.split}_per_instance.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 220)
    view = summary[(summary["radius_km"] == 1)].pivot_table(index="config", columns="bundle",
                                                            values=["nDCG@10", "bad@3", "top1_ok"]).round(3)
    logger.info("%s, 1km:\n%s", args.split, view.to_string())
    logger.info("Judged@10(1km, 전체): %s", summary[(summary["radius_km"] == 1) & (summary["bundle"] == "전체")]
                .set_index("config")["Judged@10"].round(3).to_dict())
    logger.info("저장: %s", out)


if __name__ == "__main__":
    main()
