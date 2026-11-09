"""X2·X3 채점(docs/SERVICE_PIPELINE_PLAN.md 11-4, 11-9) — 반경 확장·지역 필터·지도 화면을 정책대로 흉내 내고 판정으로 잰다.

판정 라운드 service_v11(+ 필터 요청 service_v12)이 qrels에 들어간 뒤 돌린다. 판정 전 qrels로 돌리면 10km·지역 결과 대부분이 미판정이라
숫자는 뜻이 없다(Judged@10을 같이 낸다).

정책(configs/service/search_policy_v1.yaml)
  관련 = X1 확률 P(관련) ≥ threshold_p(results/service_pipeline/x1/calibrator.json), 브랜드 쿼리의 브랜드 지점은 확률 없이 관련.
  expand        1km 안 관련 가게가 N개 이상이면 1km 관련 가게만, 아니면 10km 안 관련 가게(정렬 방식에 따라). 10km에도 없으면 "없음".
  region_point  지역 중심에서 같은 규칙(1km → 10km).
  region_area   지역(법정동 코드) 안 관련 가게, 유사도순.
  map5          화면 안 관련 가게 전부(지도 모드 — 확장 없음).
정렬 방식(expand·region_point의 최종 목록): sim(유사도순, 회의안) / tier(1km 관련 먼저, 그다음 유사도순) / decay2·decay5(점수 × 2^(−거리/h)).
지표: 사례 결과 — 헛된 "없음"(10km(또는 범위) 안 정답이 있는데 아무것도 안 보임), nDCG@10·bad@3·top1(정답 있는 요청), 확장 비율,
상위 3개 평균 거리, Judged@10. 지도: 노출 정밀도, 헛된 "없음".

    python scripts/eval_x23.py                # dev(결정용)
    python scripts/eval_x23.py --split test   # X7: 정책 파일의 N·정렬 하나만 계산
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_x23_round import (
    DENSE,
    MAX_KM,
    clean_runs,
    load_corpus,
    load_expansion,
    load_requests,
    load_runs_x23,
    p0_pending,
    policy_runs,
)
from eval_service_pipeline import BRAND_MIN, load_pair_cosine

from store_search_ai.data.service_pool import filter_mask, haversine_km
from store_search_ai.evaluation.threshold import BINARY, add_features
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)
OUT = Path("results/service_pipeline/x23")
N_GRID = (1, 3, 5, 10)
ORDERS = ("sim", "tier", "tier@0.5", "tier@0.6", "tier@0.7", "decay2", "decay5")   # tier@X: 1km 먼저는 P ≥ X만(P0)


def policy_order(policy: dict) -> str:
    """정책의 확장 정렬 이름: expanded_order(tier) + tier_min_p(있으면 'tier@0.5')."""

    o = policy["ranking"]["expanded_order"]
    t = policy["ranking"].get("tier_min_p")
    return f"tier@{t:g}" if o == "tier" and t is not None else o


def tier_order(shown: list, near: set, prob: dict, brand: set, strong: float) -> list:
    """확장 목록 순서(P0, 2026-11-05): 브랜드 지점(가까운 순) → 1km 안 '강한' 관련 가게(P ≥ strong) → 나머지 유사도순.
    strong = τ면 예전 '1km 먼저'(모든 1km 관련 가게가 10km 가게 위). 브랜드 지점은 거리순 결정(ranking.brand_sort)이라 늘 맨 위."""

    b = [d for d in shown if d in brand]
    first = [d for d in shown if d not in brand and d in near and prob[d] >= strong]
    lead = set(b) | set(first)
    return b + first + [d for d in shown if d not in lead]


def relevance_probability(stage: pd.DataFrame, raw: pd.DataFrame, req: pd.DataFrame, calibrator: dict,
                          intents: dict[str, str]) -> pd.Series:
    """1단계 후보마다 P(관련) — X1 로지스틱. 특성은 요청 후보 기준(점수는 브랜드 지점을 뺀 1단계 점수)."""

    bm = raw[raw["system"] == "char_bm25"][["query_id", "doc_id", "score"]].rename(columns={"query_id": "instance_id",
                                                                                           "score": "bm25"})
    f = stage.rename(columns={"query_id": "instance_id"})[["instance_id", "doc_id", "score"]]
    f = add_features(f.merge(bm.drop_duplicates(["instance_id", "doc_id"]), on=["instance_id", "doc_id"], how="left"))
    p = np.zeros(len(f))
    for g, coef in calibrator["groups"].items():
        m = f["instance_id"].map(lambda i: "name" if intents.get(i) in ("name", "brand") else "category").to_numpy() == g
        z = coef["intercept"] + sum(coef["coef"][k] * f.loc[m, k].to_numpy() for k in calibrator["features"])
        p[m] = 1 / (1 + np.exp(-z))
    return pd.Series(p, index=pd.MultiIndex.from_arrays([f["instance_id"], f["doc_id"]]))


def within_km(raw: pd.DataFrame, req: pd.DataFrame, corpus: pd.DataFrame, km: float) -> np.ndarray:
    """run 행이 그 요청 중심에서 km 안인가."""

    loc = req.set_index("query_id")[["latitude", "longitude"]]
    c = corpus.set_index("doc_id")[["latitude", "longitude"]]
    ok = np.zeros(len(raw), dtype=bool)
    for qid, ix in raw.groupby("query_id").indices.items():
        if qid not in loc.index:
            continue
        d = c.loc[raw["doc_id"].to_numpy()[ix]]
        ok[ix] = haversine_km(float(loc.at[qid, "latitude"]), float(loc.at[qid, "longitude"]), d["latitude"].to_numpy(float),
                              d["longitude"].to_numpy(float)) <= km + 1e-9
    return ok


def dcg(grades: list[int]) -> float:
    return float(sum((2 ** g - 1) / np.log2(i + 2) for i, g in enumerate(grades)))


def score_list(docs: list[str], judged: dict[str, int], pool_rel: list[int]) -> dict:
    grades = [judged.get(d, 0) for d in docs[:10]]
    ideal = sorted(pool_rel, reverse=True)[:10]
    return {"nDCG@10": dcg(grades) / dcg(ideal) if ideal and dcg(ideal) > 0 else np.nan,
            "bad@3": float(not any(judged.get(d, -1) >= BINARY for d in docs[:3])),
            "top1_ok": float(bool(docs) and judged.get(docs[0], -1) >= BINARY),
            "Judged@10": float(np.mean([d in judged for d in docs[:10]])) if docs else np.nan}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--policy", default="configs/service/search_policy_v1.yaml")
    parser.add_argument("--category-gamma", type=float, help="업종 가산점 γ(기본: 정책 category.boost_gamma). dev 비교용")
    parser.add_argument("--expansion-w", type=float, help="LLM 쿼리 확장 가중치(기본: 정책 ranking.expansion_w). dev 비교용")
    parser.add_argument("--brand-others-min", type=float, help="브랜드 쿼리에서 지점 아닌 가게의 최소 관련 확률(기본: 정책). dev 비교용")
    parser.add_argument("--calibrator", help="관련 확률 계수 파일(기본: 정책 relevance.calibrator) — P2(c) 비교용")
    parser.add_argument("--full-cosine", action="store_true", help="P2(a): 임베딩 상위 50 밖 후보에 실제 v1 코사인(results/service_pipeline/p2)")
    parser.add_argument("--cosine-scope", choices=["all", "name"], default="all", help="--full-cosine 범위: 모든 후보 / 상호 일치 후보만")
    parser.add_argument("--dump", action="store_true", help="정책 구성의 노출 목록(상위 20)을 shown_<split><suffix>.csv로 — 정성 점검용")
    parser.add_argument("--suffix", default="", help="출력 파일 이름 뒤에 붙임")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, bench, policy = load_config(args.config), load_config(args.benchmark_config), load_config(args.policy)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    tau = float(policy["relevance"]["threshold_p"])
    brand_others = (args.brand_others_min if args.brand_others_min is not None
                    else float(policy["ranking"].get("brand_others_min_p", tau)))
    # test는 정책 파일에 정한 구성 하나만 계산한다(X7 — test로 고르지 않는다, docs/EVALUATION_POLICY.md)
    n_grid, orders = (((int(policy["radius"]["expand_if_relevant_below"]),), (policy_order(policy),))
                      if args.split == "test" else (N_GRID, ORDERS))
    calibrator = json.loads(Path(args.calibrator or policy["relevance"]["calibrator"]).read_text(encoding="utf-8"))
    if args.calibrator:   # 비교용 계수 파일이면 그 파일의 임계값을 쓴다
        tau = float(calibrator["threshold_p"])

    req = load_requests(cfg)
    req = req[req["split"] == args.split].reset_index(drop=True)
    corpus = load_corpus(bench)
    raw = load_runs_x23(bdir, req)
    raw = raw[raw["query_id"].isin(req["query_id"])]
    if DENSE not in set(raw["system"]):
        raise SystemExit("임베딩 run이 없습니다")
    raw, stale, notes = clean_runs(raw, req, corpus, bdir)
    # 임베딩 결과가 없는 요청(지명 사전 수정으로 범위가 바뀐 요청 중 일부)은 1단계 순위를 흉내 낼 수 없어 채점에서 뺀다
    pending = p0_pending(bdir)                              # P0으로 범위가 바뀌어 새 임베딩 run을 기다리는 요청
    if pending:
        logger.warning("P0 새 run 대기 요청 %d개는 뺀다: %s", len(pending), sorted(pending))
    req = req[~req["query_id"].isin(stale | set(notes["dense_missing_requests"]) | pending)].reset_index(drop=True)
    raw = raw[raw["query_id"].isin(req["query_id"])]
    gamma = args.category_gamma if args.category_gamma is not None else float(policy["category"].get("boost_gamma", 0.0))
    cats = pd.read_parquet(policy["category"]["store_labels"]).set_index("doc_id")["category"] if gamma > 0 else None
    ew = args.expansion_w if args.expansion_w is not None else float(policy["ranking"].get("expansion_w", 0.0))
    expansion = load_expansion(ew, policy["ranking"].get("expansion_llm", "Qwen2.5-14B-Instruct"), corpus)
    scope = args.cosine_scope if args.full_cosine else policy["ranking"].get("real_cosine", "off")   # 기본은 정책 값
    cosine = load_pair_cosine() if scope != "off" else None
    args.cosine_scope = scope
    runs = policy_runs(raw, req, corpus, gamma, cats, expansion, cosine, args.cosine_scope)
    logger.info("업종 가산점 γ = %.2f", gamma)
    intents = dict(zip(req["query_id"], req["intent"], strict=True))
    sim = runs["sim"]
    base = runs["sim_base"]
    p = relevance_probability(base[base["score"] < BRAND_MIN], raw, req, calibrator, intents)   # 10km 단계(업종 가산점 전 점수)
    # 1km 단계: 서비스처럼 1km 후보만으로 1단계를 다시 만들어(점수 정규화·쿼리 안 순위·BM25 비율이 1km 기준) 확률을 계산한다
    circle = req[req["kind"].isin(["expand", "region_point"])]
    raw1 = raw[raw["query_id"].isin(circle["query_id"]) & within_km(raw, circle, corpus, 1.0)]
    base1 = policy_runs(raw1, circle, corpus, expansion=expansion and {**expansion, "km": 1.0}, cosine=cosine,
                         cosine_scope=args.cosine_scope)["sim_base"]
    p1 = relevance_probability(base1[base1["score"] < BRAND_MIN], raw1, circle, calibrator, intents)

    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    judged_by_q = {q: dict(zip(g["doc_id"], g["relevance"], strict=True)) for q, g in qrels.groupby("query_id")}
    c = corpus.set_index("doc_id")
    rows, dump = [], []
    pol_n, pol_order = int(policy["radius"]["expand_if_relevant_below"]), policy_order(policy)

    def keep_dump(r, shown, docs, dist, prob, judged, expanded):
        pos = {d: i for i, d in enumerate(docs)}
        for k, d in enumerate(shown[:20]):
            i = pos[d]
            dump.append({"query_id": r.query_id, "kind": r.kind, "query": r.query, "region_text": r.region_text, "expanded": expanded,
                         "n_shown": len(shown), "rank": k + 1, "doc_id": d, "dist_km": round(float(dist[i]), 2),
                         "p": round(float(prob[i]), 3), "grade": judged.get(d, -1)})
        if not shown:
            dump.append({"query_id": r.query_id, "kind": r.kind, "query": r.query, "region_text": r.region_text, "expanded": expanded,
                         "n_shown": 0, "rank": 0})

    for r in req.itertuples():
        judged = judged_by_q.get(r.base_query_id, {})
        s = sim[sim["query_id"] == r.query_id]
        docs = s["doc_id"].to_numpy()
        if len(docs) == 0:
            continue
        lat, lon = c.loc[docs, "latitude"].to_numpy(float), c.loc[docs, "longitude"].to_numpy(float)
        dist = haversine_km(float(r.latitude), float(r.longitude), lat, lon)
        is_brand = (s["score"] >= BRAND_MIN).to_numpy()
        within1 = dist <= 1.0 + 1e-9
        circle_req = r.kind in ("expand", "region_point")
        prob = np.array([1.0 if b else (p1.get((r.query_id, d), 0.0) if circle_req and w else p.get((r.query_id, d), 0.0))
                         for d, b, w in zip(docs, is_brand, within1, strict=True)])
        rel_shown = prob >= tau
        brand_set = set(docs[is_brand])
        if brand_set:   # 브랜드 쿼리: 지점이 아닌 가게는 더 높은 확률만(BHC 쿼리에 BYC 같은 이름 닮은 가게를 막는다)
            rel_shown = rel_shown & (is_brand | (prob >= brand_others))
        pmap = dict(zip(docs, prob, strict=True))
        # 이 요청 범위에서 판정된 정답(판정 위치와 무관 — 범위 안 가맹점 전부: 반경 요청은 10km 안, 지역·지도는 필터 안)
        jd = [d for d in judged if d in c.index]
        jl, jo = c.loc[jd, "latitude"].to_numpy(float), c.loc[jd, "longitude"].to_numpy(float)
        inside = filter_mask(r.code_prefix, r.bbox, c.loc[jd, "legal_dong_code"].astype(str).to_numpy(), jl, jo)
        if inside is None:
            inside = haversine_km(float(r.latitude), float(r.longitude), jl, jo) <= MAX_KM + 1e-6
        pool_rel = [judged[d] for d, k in zip(jd, inside, strict=True) if k]
        answerable = any(g >= BINARY for g in pool_rel)
        base = {"query_id": r.query_id, "kind": r.kind, "bundle": r.bundle, "intent": r.intent, "answerable": answerable}
        if r.kind in ("region_area", "map5"):
            shown = list(docs[rel_shown])
            keep_dump(r, shown, docs, dist, prob, judged, False)
            out = {**base, "N": 0, "order": "sim", "expanded": False, "n_shown": len(shown), "none": not shown,
                   "precision": (float(np.mean([judged.get(d, 0) >= BINARY for d in shown if d in judged]))
                                 if any(d in judged for d in shown) else np.nan),
                   **score_list(shown, judged, [g for g in pool_rel])}
            rows.append(out)
            continue
        n1 = int((rel_shown & within1).sum())
        for n in n_grid:
            expanded = n1 < n
            for order in orders:
                if not expanded:
                    shown = list(docs[rel_shown & within1])
                else:
                    o = runs[order] if order.startswith("decay") else sim
                    ranked = o[o["query_id"] == r.query_id]["doc_id"].tolist() if order.startswith("decay") else list(docs)
                    keep = dict(zip(docs, rel_shown, strict=True))
                    shown = [d for d in ranked if keep.get(d, False)]
                    if order.startswith("tier"):
                        strong = float(order.split("@")[1]) if "@" in order else tau
                        shown = tier_order(shown, set(docs[within1]), pmap, brand_set, strong)
                if n == pol_n and order == pol_order:
                    keep_dump(r, shown, docs, dist, prob, judged, expanded)
                pos = {d: i for i, d in enumerate(docs)}
                top3 = [dist[pos[d]] for d in shown[:3]]
                rows.append({**base, "N": n, "order": order, "expanded": expanded, "n_shown": len(shown), "none": not shown,
                             "top3_mean_km": float(np.mean(top3)) if top3 else np.nan,
                             **score_list(shown, judged, pool_rel)})
    per = pd.DataFrame(rows)
    per["false_none"] = per["answerable"] & per["none"]
    OUT.mkdir(parents=True, exist_ok=True)
    per.to_csv(OUT / f"per_request_{args.split}{args.suffix}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    if args.dump:
        d = pd.DataFrame(dump).merge(corpus[["doc_id", "store_name", "item_text", "market_name"]], on="doc_id", how="left")
        d.to_csv(OUT / f"shown_{args.split}{args.suffix}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    ans = per[per["answerable"]]
    summary = (per.groupby(["kind", "N", "order"]).agg(requests=("query_id", "size"), expanded=("expanded", "mean"),
                                                        false_none=("false_none", "mean"), mean_shown=("n_shown", "mean"),
                                                        top3_km=("top3_mean_km", "mean"))
               .join(ans.groupby(["kind", "N", "order"])[["nDCG@10", "bad@3", "top1_ok", "Judged@10"]].mean())
               .join(per.groupby(["kind", "N", "order"])["precision"].mean() if "precision" in per else None)
               .reset_index())
    summary.to_csv(OUT / f"summary_{args.split}{args.suffix}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 250)
    logger.info("%s (τ = %.2f):\n%s", args.split, tau, summary.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
