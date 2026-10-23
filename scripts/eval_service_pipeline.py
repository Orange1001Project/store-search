"""서비스셋으로 검색 파이프라인 구성을 비교한다(docs/SERVICE_PIPELINE_PLAN.md). 기본은 dev만 채점한다 — test는 단계가 끝날 때
`--split test`로 고른 구성 하나만(`--only`).

실험(--exp)
  hybrid   v1 + char BM25: RRF(k=10·30·60), min-max 가중합(v1 가중치 α=0.1~0.9). 기준 = v1 단독, BM25 단독
  hybrid2  상호 일치 가산점(name match boost): v1+이름, 가중합+이름
  rerank   1단계(v1+이름 β=0.5, 1-1 채택) 반경 안 상위 k개를 reranker로 재정렬, 1단계 점수와 결합, 재정렬 뒤 상호 일치
           1) --exp rerank --export-pairs → results/service_pipeline/rerank/rerank_pairs.csv(dev+test 쌍, 위치 무관이라 쿼리 단위)
              → Drive store-search-ai/stack_eval/service/에 올리고 colab/rerank_scores.ipynb(SPLIT="service") 실행
           2) 생긴 rerank_scores_<모델>.csv를 results/service_pipeline/rerank/에 넣고 --exp rerank

출력: results/service_pipeline/<exp>_<split>.csv — 구성 × 반경 × 묶음별 nDCG@10, nDCG@10(판정만), Judged@10, bad@3, top1_ok

사용법:
    python scripts/eval_service_pipeline.py --exp hybrid
    python scripts/eval_service_pipeline.py --exp hybrid --split test --only "convex a=0.7"
    python scripts/eval_service_pipeline.py --exp rerank --export-pairs
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.evaluation.service_eval import attach_distance, instance_qrels, score_system
from store_search_ai.pipeline.common import load_config
from store_search_ai.retrieval.fusion import _rerank, boost, convex, name_match, rrf

logger = logging.getLogger(__name__)
V1 = "bge_m3_ft_mj_20261014_0743"
RERANK_DIR = Path("results/service_pipeline/rerank")
RERANK_DEPTH = 50          # 재정렬 후보 수(반경 안 1단계 상위). 실험은 이 안에서 k=20·30·50을 본다
DOC_TEXT_COLUMN = "search_text_t1_minimal"   # 모델 평가·판정 pool과 같은 문서 텍스트(가맹점명 + 취급품목)


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


def first_stage(runs: dict[str, pd.DataFrame], instances: pd.DataFrame, names: pd.Series) -> pd.DataFrame:
    """1-1에서 채택한 1단계: v1 + BM25 후보 합집합에 상호 일치 가산점 β=0.5."""

    v1 = runs[V1][runs[V1]["query_id"].isin(instances["instance_id"])]
    bm25 = runs["char_bm25"][runs["char_bm25"]["query_id"].isin(instances["instance_id"])]
    union = convex([v1, bm25], [1.0, 0.0], name="union_v1")
    return boost(union, name_hits(union, instances, names), 0.5, "v1+name b=0.5")


def within_radius(run: pd.DataFrame, instances: pd.DataFrame, coords: pd.DataFrame, radius_km: float,
                  depth: int | None = None) -> pd.DataFrame:
    """반경 안 결과만 남기고 순위를 다시 매긴다(서비스는 반경 안에서 상위 k개를 재정렬하므로 반경마다 후보가 다르다)."""

    r = attach_distance(run.rename(columns={"query_id": "instance_id"}), instances, coords)
    r = r[r["dist_km"] <= radius_km].sort_values(["instance_id", "rank"])
    r = r.assign(rank=r.groupby("instance_id").cumcount() + 1).rename(columns={"instance_id": "query_id"})
    if depth is not None:
        r = r[r["rank"] <= depth]
    return r[list(run.columns)].reset_index(drop=True)


def rerank_pairs(stage: pd.DataFrame, instances: pd.DataFrame, coords: pd.DataFrame, radii: list[float],
                 doc_text: pd.Series) -> pd.DataFrame:
    """반경마다 1단계 상위 RERANK_DEPTH개 → (쿼리, 가맹점) 쌍. reranker 점수는 위치와 무관해 쿼리 단위로 한 번만 채점한다."""

    base = instances.set_index("instance_id")[["query_id", "query"]]
    top = pd.concat([within_radius(stage, instances, coords, r, RERANK_DEPTH) for r in radii])
    pairs = top[["query_id", "doc_id"]].rename(columns={"query_id": "instance_id"}).join(base, on="instance_id")
    pairs = pairs.drop_duplicates(["query_id", "doc_id"]).sort_values(["query_id", "doc_id"])
    return pairs.assign(doc_text=pairs["doc_id"].map(doc_text).fillna(""))[["query_id", "doc_id", "query", "doc_text"]]


def load_rerank_scores() -> dict[str, pd.DataFrame]:
    return {p.stem.removeprefix("rerank_scores_"): pd.read_csv(p, encoding="utf-8-sig")
            for p in sorted(RERANK_DIR.glob("rerank_scores_*.csv"))}


def rerank_variants(stage_r: pd.DataFrame, scores: dict[str, pd.DataFrame], instances: pd.DataFrame,
                    names: pd.Series) -> dict[str, pd.DataFrame]:
    """반경 안으로 자른 1단계(stage_r)의 상위 k개를 reranker 점수만으로 / 1단계와 가중합으로 재정렬하고, k 밖은 1단계 순서대로 뒤에 둔다.
    재정렬 뒤 상호 일치 가산점도 본다(reranker가 정확한 상호를 내리는지)."""

    base = instances.set_index("instance_id")["query_id"]
    out = {"v1+name b=0.5": stage_r}
    for model, sc in scores.items():
        key = dict(zip(zip(sc["query_id"], sc["doc_id"], strict=True), sc["score"], strict=True))
        for k in (20, 30, RERANK_DEPTH):
            head, tail = stage_r[stage_r["rank"] <= k], stage_r[stage_r["rank"] > k]
            rr = head.assign(score=[key.get((base[i], d), np.nan) for i, d in zip(head["query_id"], head["doc_id"], strict=True)])
            if rr["score"].isna().any():
                raise SystemExit(f"{model}: reranker 점수 없는 쌍 {int(rr['score'].isna().sum())}개 — --export-pairs부터 다시")
            variants = {f"rr {model} k={k}": rr}
            if k == RERANK_DEPTH:
                for a in (0.3, 0.5, 0.7):          # a = reranker 가중치
                    variants[f"rr {model} k={k} mix a={a}"] = convex([rr, head], [a, 1 - a])
                variants[f"rr {model} k={k} +name b=0.5"] = boost(rr, name_hits(rr, instances, names), 0.5, "rr+name")
            for name, v in variants.items():
                v = _rerank(v[["query_id", "doc_id", "score"]], name)
                rest = tail.assign(rank=tail["rank"] + 10_000, system=name)   # k 밖은 재정렬 결과 뒤에 1단계 순서대로
                out[name] = pd.concat([v, rest[v.columns]], ignore_index=True)
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
    parser.add_argument("--exp", choices=["hybrid", "hybrid2", "rerank"], required=True)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--only", action="append", help="채점할 구성 이름(여러 번). test는 반드시 지정")
    parser.add_argument("--export-pairs", action="store_true", help="rerank: Colab에서 채점할 쌍만 내보내고 끝")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.split == "test" and not args.only:
        raise SystemExit("test는 고른 구성만 채점합니다 — --only로 지정하세요(docs/SERVICE_PIPELINE_PLAN.md 3절).")
    if args.export_pairs and args.exp != "rerank":
        raise SystemExit("--export-pairs는 --exp rerank에서만 씁니다")

    cfg = load_config(args.config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    bench = load_config(args.benchmark_config)
    all_instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    instances = all_instances[all_instances["split"] == args.split]
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]
    radii = cfg["judging"]["report_radii_km"]
    runs = load_runs(bdir)
    names = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name"]).set_index("doc_id")["store_name"]

    if args.export_pairs:
        doc_text = pd.read_parquet(bench["corpus_path"], columns=["doc_id", DOC_TEXT_COLUMN]).set_index("doc_id")[DOC_TEXT_COLUMN]
        # dev와 test 쌍을 한 번에 내보낸다(Colab 한 번). 점수만 받아 두고 test 지표는 단계 끝에 한 번만 계산한다.
        pairs = rerank_pairs(first_stage(runs, all_instances, names), all_instances, coords, radii, doc_text)
        RERANK_DIR.mkdir(parents=True, exist_ok=True)
        pairs.to_csv(RERANK_DIR / "rerank_pairs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
        logger.info("쌍 %d개(쿼리 %d개) → %s", len(pairs), pairs["query_id"].nunique(), RERANK_DIR / "rerank_pairs.csv")
        return

    iq = instance_qrels(instances, qrels, coords)
    if args.exp == "rerank":
        scores = load_rerank_scores()
        if not scores:
            raise SystemExit(f"{RERANK_DIR}/rerank_scores_*.csv가 없습니다 — 먼저 --export-pairs 후 Colab에서 채점하세요")
        stage = first_stage(runs, instances, names)

        def variants_for(radius: float) -> dict[str, pd.DataFrame]:
            return rerank_variants(within_radius(stage, instances, coords, radius), scores, instances, names)
    else:
        fixed = hybrid_variants(runs) if args.exp == "hybrid" else hybrid2_variants(runs, instances, names)

        def variants_for(radius: float) -> dict[str, pd.DataFrame]:
            return fixed
    per = []
    for radius in radii:
        variants = variants_for(radius)
        if args.only:
            variants = {k: v for k, v in variants.items() if k in set(args.only) | {"v1", "v1+name b=0.5"}}
        for name, run in variants.items():
            run = run[run["query_id"].isin(instances["instance_id"])]
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
