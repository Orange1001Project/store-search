"""X8(docs/SERVICE_PIPELINE_PLAN.md 11-16·11-17) — 상황·추상 쿼리 실패를 겨냥한 두 실험을 1단계(11-8 최종 구성)에 붙여 dev로 비교한다.

  ① reranker 가산: 반경 안 1단계 상위 k개(브랜드 지점 제외)에 a × reranker 확률을 더한다(1단계 점수·상호 일치 가산점은 그대로 —
     예전 1-4 실험은 reranker 점수로 갈아 끼워 상호 쿼리를 잃었다). 적용 범위: 모든 쿼리 / 업종 의도 쿼리만.
  ② LLM 쿼리 확장: 확장어(찾는 가게 종류·품목)로 반경 안 가맹점을 문자 BM25 채점 → 사례 안 최댓값으로 나눠 w배 더한다.
     1단계에 없던 가게는 확장 상위 200개까지 후보에 더한다(1단계 점수는 사례 최솟값). 업종 의도 쿼리만(상호·브랜드 쿼리는
     가게를 이미 알고 찾으므로 확장이 해만 된다 — Query2doc, Wang et al. EMNLP 2023도 키워드 질의에서 이득이 크다).

새로 들어온 가게는 판정이 안 됐을 수 있다 — 판정만 남긴 nDCG(condensed, Sakai 2007)와 Judged@10을 같이 보고,
고를 만하면 보충 판정 후 다시 잰다.

입력: results/service_pipeline/rerank/rerank_scores_<모델>.csv(1-4) + results/service_pipeline/x8/rerank_scores_<모델>.csv(X8 추가분),
      results/service_pipeline/x8/expansions_<LLM>.csv
출력: results/service_pipeline/x8/x8_{split}[_all].csv(구성 × 반경 × 묶음), x8_{split}[_all]_paired.csv(기준 대비 차이·CI)
사용법:
    python scripts/eval_x8.py                       # dev 주 평가셋
    python scripts/eval_x8.py --set all             # dev 모든 사례(견고성)
    python scripts/eval_x8.py --split test --only "..."   # 마지막에 한 번
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_service_pipeline import (
    BRAND_MIN,
    RERANK_DIR,
    V1,
    _agg,
    alias_name_hits,
    brand_distance_sort,
    load_runs,
    parsed_queries,
    summarize,
    union_v1,
    within_radius,
    write_pool_round,
)

from store_search_ai.data.service_pool import haversine_km
from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    condense,
    instance_qrels,
    load_bundle_overrides,
    paired,
    score_system,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.query.aliases import BrandAliases
from store_search_ai.retrieval.expansion import (
    SparseBM25,
    add_expansion,
    expansion_frame,
    load_expansions,
)
from store_search_ai.retrieval.fusion import _rerank, boost
from store_search_ai.retrieval.lexical import build_pool_document_texts

logger = logging.getLogger(__name__)
X8_DIR = Path("results/service_pipeline/x8")
BASE = "stage1"
RR_K = 50                 # 재정렬 범위(반경 안 1단계 상위 — X8 채점 쌍의 깊이)
RR_A = (0.25, 0.5, 1.0)
EXP_W = (0.1, 0.2, 0.3, 0.5)


def load_rerank(model: str) -> pd.DataFrame:
    paths = [p for p in (RERANK_DIR / f"rerank_scores_{model}.csv", X8_DIR / f"rerank_scores_{model}.csv") if p.exists()]
    if not paths:
        raise SystemExit(f"rerank_scores_{model}.csv가 없습니다")
    sc = pd.concat([pd.read_csv(p, encoding="utf-8-sig") for p in paths], ignore_index=True)
    return sc.drop_duplicates(["query_id", "doc_id"], keep="last")


def rerank_add(stage_r: pd.DataFrame, rr: dict, base: pd.Series, targets: set, a: float, name: str) -> pd.DataFrame:
    """상위 RR_K개(브랜드 지점 빼고, targets 사례만)에 a × reranker 확률을 더한다."""

    s = stage_r.copy()
    m = (s["rank"] <= RR_K) & (s["score"] < BRAND_MIN) & s["query_id"].isin(targets)
    keys = list(zip(s.loc[m, "query_id"].map(base), s.loc[m, "doc_id"], strict=True))
    vals = np.array([rr.get(k, np.nan) for k in keys], dtype=float)
    if np.isnan(vals).any():
        raise SystemExit(f"reranker 점수 없는 쌍 {int(np.isnan(vals).sum())}개")
    s.loc[m, "score"] = s.loc[m, "score"] + a * vals
    return _rerank(s[["query_id", "doc_id", "score"]], name)


def expansion_add(stage_r: pd.DataFrame, exp_scores: dict[str, pd.DataFrame], w: float, name: str) -> pd.DataFrame:
    return add_expansion(stage_r, pd.concat(exp_scores.values(), ignore_index=True) if exp_scores else None, w, name, BRAND_MIN)


def expansion_scores(instances: pd.DataFrame, targets: set, expansions: dict[str, str], bm25: SparseBM25,
                     lat: np.ndarray, lon: np.ndarray, doc_ids: np.ndarray, radius: float) -> dict[str, pd.DataFrame]:
    out = {}
    for r in instances[instances["instance_id"].isin(targets)].itertuples():
        rows = np.flatnonzero(haversine_km(float(r.latitude), float(r.longitude), lat, lon) <= radius)
        f = expansion_frame(r.instance_id, expansions.get(r.query_id, ""), bm25, rows, doc_ids)
        if f is not None:
            out[r.instance_id] = f
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--set", choices=["main", "all"], default="main")
    parser.add_argument("--reranker", default="bge-reranker-v2-m3")
    parser.add_argument("--llm", default="Qwen2.5-14B-Instruct")
    parser.add_argument("--only", action="append", help="채점할 구성(test는 반드시 지정)")
    parser.add_argument("--pool-round", help="확장 구성(exp)들의 반경별 상위 10 중 미판정 쌍 → 판정 라운드(dev+test 모든 사례, 예: service_v12)")
    parser.add_argument("--dry-run", action="store_true", help="--pool-round: 판정 건수만")
    parser.add_argument("--pool-w", type=float, nargs="+", default=list(EXP_W), help="--pool-round: 판정할 확장 가중치")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.split == "test" and not args.only and not args.pool_round:
        raise SystemExit("test는 고른 구성만 — --only로 지정하세요")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    inst = apply_eval_bundle(inst, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    instances = inst if args.pool_round else inst[inst["split"] == args.split]
    if args.set == "main" and not args.pool_round:
        main_ids = pd.read_csv(cfg["eval_set"]["output"], encoding="utf-8-sig")["instance_id"]
        instances = instances[instances["instance_id"].isin(main_ids)]
    instances = instances.reset_index(drop=True)
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    corpus = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "latitude", "longitude",
                                                            "geo_status"])
    corpus = corpus[corpus["geo_status"] == "VALID"].reset_index(drop=True)
    coords = corpus[["doc_id", "latitude", "longitude"]]
    names = corpus.set_index("doc_id")["store_name"]
    radii = cfg["judging"]["report_radii_km"]

    runs = load_runs(bdir)
    ids = set(instances["instance_id"])
    parsed = parsed_queries(instances, bench["corpus_path"])
    aliases = BrandAliases.load()
    v1 = runs[V1][runs[V1]["query_id"].isin(ids)]
    bm = runs["char_bm25"][runs["char_bm25"]["query_id"].isin(ids)]
    union = union_v1(v1, bm)
    stage = boost(union, alias_name_hits(union, dict(zip(parsed["instance_id"], parsed["name_key"], strict=True)), names, aliases),
                  0.5, BASE)
    stage = brand_distance_sort(stage, instances, parsed, corpus, aliases, max(radii), BASE)
    category = set(parsed.loc[parsed["intent"] == "category", "instance_id"])
    logger.info("사례 %d개(업종 의도 %d개)", len(instances), len(category))

    base = instances.set_index("instance_id")["query_id"]
    sc = load_rerank(args.reranker)
    rr = dict(zip(zip(sc["query_id"], sc["doc_id"], strict=True), sc["score"], strict=True))
    expansions = load_expansions(X8_DIR / f"expansions_{args.llm}.csv")
    logger.info("문자 BM25 색인(가맹점 %d곳)", len(corpus))
    bm25 = SparseBM25(build_pool_document_texts(corpus))
    lat, lon, doc_ids = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float), corpus["doc_id"].to_numpy()

    if args.pool_round:   # 판정은 위치와 무관한 (쿼리, 가맹점) 단위 — dev·test 모든 사례를 한 라운드로(test 채점도 공정하게)
        tops = []
        for radius in radii:
            stage_r = within_radius(stage, instances, coords, radius)
            exp = expansion_scores(instances, category, expansions, bm25, lat, lon, doc_ids, radius)
            for w in args.pool_w:
                name = f"exp+{w} cat"
                tops.append(within_radius(expansion_add(stage_r, exp, w, name), instances, coords, radius,
                                          cfg["judging"]["depth"]).assign(system=name))
        write_pool_round(cfg, bench, tops, instances, args.pool_round, args.dry_run,
                         {"set": "X8 LLM 쿼리 확장 보충 판정(확장 구성, dev+test 모든 사례)", "first_stage": BASE + "(11-8 최종)",
                          "expansion_llm": args.llm})
        return

    iq = instance_qrels(instances, qrels, coords)
    per = []
    for radius in radii:
        stage_r = within_radius(stage, instances, coords, radius)
        exp = expansion_scores(instances, category, expansions, bm25, lat, lon, doc_ids, radius)
        variants = {BASE: stage_r}
        for a in RR_A:
            variants[f"rr+{a} all"] = rerank_add(stage_r, rr, base, ids, a, f"rr+{a} all")
            variants[f"rr+{a} cat"] = rerank_add(stage_r, rr, base, category, a, f"rr+{a} cat")
        for w in EXP_W:
            variants[f"exp+{w} cat"] = expansion_add(stage_r, exp, w, f"exp+{w} cat")
        if args.only:
            variants = {k: v for k, v in variants.items() if k in set(args.only) | {BASE}}
        for name, run in variants.items():
            s = score_system(run, iq, instances, coords, radius)
            c = score_system(condense(run, instances, qrels), iq, instances, coords, radius)
            s = s.merge(c[["instance_id", "nDCG@10"]].rename(columns={"nDCG@10": "nDCG@10_condensed"}), on="instance_id")
            per.append(s.assign(config=name, radius_km=radius))
    per = pd.concat(per, ignore_index=True).merge(instances[["instance_id", "bundle"]], on="instance_id")
    per["category"] = per["instance_id"].isin(category)
    summary = summarize(per)
    rows = [{"config": k[0], "radius_km": k[1], "bundle": "업종 의도", **_agg(g)}
            for k, g in per[per["category"]].groupby(["config", "radius_km"])]
    summary = pd.concat([summary, pd.DataFrame(rows)], ignore_index=True)

    comp = []
    for (name, radius), g in per.groupby(["config", "radius_km"]):
        if name == BASE:
            continue
        b = per[(per["config"] == BASE) & (per["radius_km"] == radius)].set_index("instance_id")
        g = g.set_index("instance_id")
        for metric in ("nDCG@10", "nDCG@10_condensed", "bad@3", "top1_ok"):
            comp.append({"config": name, "radius_km": radius, "metric": metric, **paired(g[metric], b[metric].reindex(g.index))})
    comp = pd.DataFrame(comp)

    X8_DIR.mkdir(parents=True, exist_ok=True)
    tag = f"{args.split}{'_all' if args.set == 'all' else ''}"
    summary.to_csv(X8_DIR / f"x8_{tag}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    comp.to_csv(X8_DIR / f"x8_{tag}_paired.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 220)
    view = summary[summary["bundle"].isin(["전체", "업종 의도"])][
        ["config", "radius_km", "bundle", "instances", "nDCG@10", "nDCG@10_condensed", "Judged@10", "bad@3", "top1_ok"]]
    print(view.round(3).to_string(index=False))
    print(comp[comp["metric"].isin(["nDCG@10", "nDCG@10_condensed", "bad@3"])].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
