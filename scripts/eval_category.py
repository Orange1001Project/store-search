"""X4 업종 신호 확인(docs/SERVICE_PIPELINE_PLAN.md 11-14) — 임시 업종 v0(data/category/store_category_v0.parquet)이 성능을 올리는지 dev에서 본다.

쿼리 업종은 학습 없이 1단계 상위 결과의 업종 분포로 정한다(상위 검색 결과로 쿼리 범주를 정하는 방식 — APRF-Net, arXiv 2104.11384):
사례 반경 안 1단계 상위 PRF_K개의 대표 업종을 순위 가중(1/log2(순위+1))으로 모은 분포(기타 제외). 가게의 '업종 일치도' cat_share = 그 분포에서
그 가게 대표 업종의 비중(0~1). 쓰는 곳 두 가지를 비교한다.
  ① X1 관련 판단: 로지스틱 특성에 cat_share를 더함(logistic_bm25_cat) — 업종 쿼리의 관련/무관 변별(AUC)과 임계값 곡선
  ② 순위: 1단계 점수 + γ × cat_share(업종 쿼리만, γ = 0.1·0.2·0.3·0.5) — 1km nDCG@10·bad@3·top1
1단계 = 11-8 채택 구성(v1+BM25 합집합, 상호 일치·별칭 β=0.5, 브랜드 거리순). 브랜드 지점은 확률 없이 관련(학습·보정에서 뺀다).

    python scripts/eval_category.py      # dev(모든 사례로 보정·주 평가셋도 같이 보고)
출력: results/service_pipeline/category/{calibration,curve,ranking}_dev.csv
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_relevance_threshold import GRID, TARGET_HIDDEN, oof_predictions
from eval_service_pipeline import (
    BRAND_MIN,
    V1,
    alias_name_hits,
    brand_distance_sort,
    load_runs,
    parsed_queries,
    union_v1,
)

from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    attach_distance,
    instance_qrels,
    load_bundle_overrides,
    score_system,
)
from store_search_ai.evaluation.threshold import (
    BINARY,
    FEATURE_SETS,
    add_features,
    calibration_metrics,
    instance_outcomes,
    summarize_outcomes,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.query.aliases import BrandAliases
from store_search_ai.retrieval.fusion import _rerank, boost

logger = logging.getLogger(__name__)
OUT = Path("results/service_pipeline/category")
CATEGORY_PATH = "data/category/store_category_v0.parquet"
PRF_K = 10
GAMMAS = (0.0, 0.1, 0.2, 0.3, 0.5)


def category_share(stage: pd.DataFrame, cats: pd.Series, radius_cands: pd.DataFrame, empty: str = "ETC") -> pd.Series:
    """사례마다 반경 안 1단계 상위 PRF_K개의 업종 분포 → (사례, 가게)의 cat_share."""

    top = radius_cands.sort_values(["instance_id", "rank_r"]).groupby("instance_id").head(PRF_K)
    top = top.assign(cat=top["doc_id"].map(cats).fillna(empty), w=1 / np.log2(top["rank_r"] + 1))
    top = top[top["cat"] != empty]
    dist = top.groupby(["instance_id", "cat"])["w"].sum()
    dist = dist / dist.groupby(level=0).transform("sum")
    key = pd.MultiIndex.from_arrays([radius_cands["instance_id"], radius_cands["doc_id"].map(cats).fillna(empty)])
    return pd.Series(dist.reindex(key).fillna(0.0).to_numpy(), index=radius_cands.index)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, bench = load_config(args.config), load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    instances = apply_eval_bundle(instances, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    instances = instances[instances["split"] == "dev"].reset_index(drop=True)
    main_ids = set(pd.read_csv(cfg["eval_set"]["output"], encoding="utf-8-sig")["instance_id"])
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]
    names = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name"]).set_index("doc_id")["store_name"]
    geo = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "latitude", "longitude", "geo_status"])
    geo = geo[geo["geo_status"] == "VALID"].reset_index(drop=True)
    table = pd.read_parquet(CATEGORY_PATH).set_index("doc_id")
    cats, subs = table["category"], table["subcategory"]
    runs = load_runs(bdir)

    parsed = parsed_queries(instances, bench["corpus_path"])
    group = parsed.set_index("instance_id")["intent"].map(lambda i: "name" if i in ("name", "brand") else "category")
    cores = dict(zip(parsed["instance_id"], parsed["name_key"], strict=True))
    aliases = BrandAliases.load()
    v1 = runs[V1][runs[V1]["query_id"].isin(instances["instance_id"])]
    bm25 = runs["char_bm25"][runs["char_bm25"]["query_id"].isin(instances["instance_id"])]
    union = union_v1(v1, bm25)
    alias_run = boost(union, alias_name_hits(union, cores, names, aliases), 0.5, "alias")
    bm = bm25.rename(columns={"query_id": "instance_id", "score": "bm25"})[["instance_id", "doc_id", "bm25"]]
    bm = bm.drop_duplicates(["instance_id", "doc_id"])
    brand_rows = brand_distance_sort(alias_run, instances, parsed, geo, aliases, 2.0, "b")
    brand_pairs = set(zip(brand_rows.loc[brand_rows["score"] >= BRAND_MIN, "query_id"], brand_rows.loc[brand_rows["score"] >= BRAND_MIN, "doc_id"],
                          strict=True))
    iq = instance_qrels(instances, qrels, coords)
    OUT.mkdir(parents=True, exist_ok=True)
    FEATURE_SETS["logistic_bm25_cat"] = [*FEATURE_SETS["logistic_bm25"], "cat_share"]
    FEATURE_SETS["logistic_bm25_sub"] = [*FEATURE_SETS["logistic_bm25"], "sub_share"]
    FEATURE_SETS["logistic_bm25_cat_sub"] = [*FEATURE_SETS["logistic_bm25"], "cat_share", "sub_share"]
    models = ("logistic_bm25", "logistic_bm25_cat", "logistic_bm25_sub", "logistic_bm25_cat_sub")

    calib, curve = [], []
    for radius in cfg["judging"]["report_radii_km"]:
        r = attach_distance(alias_run.rename(columns={"query_id": "instance_id"}), instances, coords)
        r = r[r["dist_km"] <= radius][["instance_id", "doc_id", "score"]].merge(bm, on=["instance_id", "doc_id"], how="left")
        c = add_features(r)
        c["cat_share"] = category_share(alias_run, cats, c)
        c["sub_share"] = category_share(alias_run, subs, c, empty="")
        c = c.merge(instances[["instance_id", "query_id"]], on="instance_id").merge(qrels, on=["query_id", "doc_id"], how="left")
        c["group"] = c["instance_id"].map(group)
        is_brand = np.array([(i, d) in brand_pairs for i, d in zip(c["instance_id"], c["doc_id"], strict=True)])
        brand_c = c[is_brand].assign(p=1.0)               # 브랜드 지점은 확률 없이 관련 — 보정에서는 빼고 결과 집계에는 넣는다
        c = c[~is_brand].reset_index(drop=True)
        answerable = set(iq[(iq["dist_km"] <= radius) & (iq["relevance"] >= BINARY)]["instance_id"])
        judged = c["relevance"].notna().to_numpy()
        y = (c["relevance"] >= BINARY).to_numpy(int)
        for kind in models:
            p = oof_predictions(c, kind)
            for g in ("전체", "name", "category"):
                m = judged & (True if g == "전체" else (c["group"] == g).to_numpy())
                calib.append({"radius_km": radius, "model": kind, "group": g, **calibration_metrics(p[m], y[m])})
            cc = pd.concat([c.assign(p=p), brand_c], ignore_index=True)
            for t in GRID:
                for subset, ids in (("all", None), ("main", main_ids)):
                    x = cc if ids is None else cc[cc["instance_id"].isin(ids)]
                    curve.append({"radius_km": radius, "model": kind, "threshold": t, "set": subset,
                                  **summarize_outcomes(instance_outcomes(x, answerable, t))})
    calib, curve = pd.DataFrame(calib), pd.DataFrame(curve)
    calib.to_csv(OUT / "calibration_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    curve.to_csv(OUT / "curve_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    # ② 순위: 업종 쿼리만 γ × cat_share 가산 → 브랜드 거리순
    rank_rows = []
    rc = attach_distance(alias_run.rename(columns={"query_id": "instance_id"}), instances, coords)
    rc = add_features(rc[rc["dist_km"] <= 2.0][["instance_id", "doc_id", "score"]])
    idx = pd.MultiIndex.from_arrays([rc["instance_id"], rc["doc_id"]])
    shares = {"cat": pd.Series(category_share(alias_run, cats, rc).to_numpy(), index=idx),
              "sub": pd.Series(category_share(alias_run, subs, rc, empty="").to_numpy(), index=idx)}
    cat_q = set(group[group == "category"].index)
    for level, gamma in [("cat", 0.0), *((lv, g) for lv in ("cat", "sub") for g in GAMMAS if g > 0)]:
        s = alias_run.copy()
        key = pd.MultiIndex.from_arrays([s["query_id"], s["doc_id"]])
        add = shares[level].reindex(key).fillna(0.0).to_numpy() * s["query_id"].isin(cat_q).to_numpy()
        boosted = _rerank(s.assign(score=s["score"] + gamma * add)[["query_id", "doc_id", "score"]], f"g={gamma}")
        final = brand_distance_sort(boosted, instances, parsed, geo, aliases, 2.0, f"g={gamma}")
        for radius in cfg["judging"]["report_radii_km"]:
            per = score_system(final, iq, instances, coords, radius).merge(instances[["instance_id", "bundle"]], on="instance_id")
            for subset, ids in (("all", None), ("main", main_ids)):
                x = per if ids is None else per[per["instance_id"].isin(ids)]
                for b, g in [("전체", x), *x.groupby("bundle")]:
                    rank_rows.append({"level": level, "gamma": gamma, "radius_km": radius, "set": subset, "bundle": b, "instances": len(g),
                                      **{m: g[m].mean() for m in ("nDCG@10", "bad@3", "top1_ok", "Judged@10")}})
    ranking = pd.DataFrame(rank_rows)
    ranking.to_csv(OUT / "ranking_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    pd.set_option("display.width", 250)
    logger.info("① 보정(1km):\n%s", calib[calib["radius_km"] == 1].to_string(index=False))
    for kind in models:
        cur = curve[(curve["radius_km"] == 1) & (curve["set"] == "all") & (curve["model"] == kind)]
        ok = cur[cur["hidden_rate"] <= TARGET_HIDDEN]
        best = ok.loc[ok["precision_judged"].idxmax()] if len(ok) else cur.iloc[0]
        logger.info("%s: 헛된 없음 ≤ 5%% 중 최고 정밀도 P ≥ %.2f → 헛된 없음 %.3f, 정밀도 %.3f, 평균 노출 %.2f", kind, best["threshold"],
                    best["hidden_rate"], best["precision_judged"], best["mean_shown"])
    logger.info("② 순위(1km, 주 평가셋):\n%s", ranking[(ranking["radius_km"] == 1) & (ranking["set"] == "main")]
                .pivot_table(index=["level", "gamma"], columns="bundle", values=["nDCG@10", "bad@3", "top1_ok"]).round(3).to_string())


if __name__ == "__main__":
    main()
