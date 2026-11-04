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
    load_requests,
    load_runs_x23,
    policy_runs,
)

from store_search_ai.data.service_pool import haversine_km
from store_search_ai.evaluation.threshold import BINARY, add_features
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)
OUT = Path("results/service_pipeline/x23")
N_GRID = (1, 3, 5, 10)
ORDERS = ("sim", "tier", "decay2", "decay5")


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
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg, bench, policy = load_config(args.config), load_config(args.benchmark_config), load_config(args.policy)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    tau = float(policy["relevance"]["threshold_p"])
    # test는 정책 파일에 정한 구성 하나만 계산한다(X7 — test로 고르지 않는다, docs/EVALUATION_POLICY.md)
    n_grid, orders = ((int(policy["radius"]["expand_if_relevant_below"]),), (policy["ranking"]["expanded_order"],))         if args.split == "test" else (N_GRID, ORDERS)
    calibrator = json.loads(Path(policy["relevance"]["calibrator"]).read_text(encoding="utf-8"))

    req = load_requests(cfg)
    req = req[req["split"] == args.split].reset_index(drop=True)
    corpus = load_corpus(bench)
    raw = load_runs_x23(bdir, req)
    raw = raw[raw["query_id"].isin(req["query_id"])]
    if DENSE not in set(raw["system"]):
        raise SystemExit("임베딩 run이 없습니다")
    raw, stale, notes = clean_runs(raw, req, corpus, bdir)
    # 임베딩 결과가 없는 요청(지명 사전 수정으로 범위가 바뀐 요청 중 일부)은 1단계 순위를 흉내 낼 수 없어 채점에서 뺀다
    req = req[~req["query_id"].isin(stale | set(notes["dense_missing_requests"]))].reset_index(drop=True)
    raw = raw[raw["query_id"].isin(req["query_id"])]
    runs = policy_runs(raw, req, corpus)
    intents = dict(zip(req["query_id"], req["intent"], strict=True))
    sim = runs["sim"]
    brand_hit = sim["score"] >= 5.0                      # brand_distance_sort가 브랜드 지점에 준 점수(10 − 거리)
    base_stage = sim[~brand_hit]
    p = relevance_probability(base_stage, raw, req, calibrator, intents)

    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    judged_by_q = {q: dict(zip(g["doc_id"], g["relevance"], strict=True)) for q, g in qrels.groupby("query_id")}
    c = corpus.set_index("doc_id")
    rows = []
    for r in req.itertuples():
        judged = judged_by_q.get(r.base_query_id, {})
        s = sim[sim["query_id"] == r.query_id]
        docs = s["doc_id"].to_numpy()
        if len(docs) == 0:
            continue
        lat, lon = c.loc[docs, "latitude"].to_numpy(float), c.loc[docs, "longitude"].to_numpy(float)
        dist = haversine_km(float(r.latitude), float(r.longitude), lat, lon)
        is_brand = (s["score"] >= 5.0).to_numpy()
        prob = np.array([1.0 if b else p.get((r.query_id, d), 0.0) for d, b in zip(docs, is_brand, strict=True)])
        rel_shown = prob >= tau
        # 이 요청 범위에서 판정된 정답(판정 위치와 무관 — 범위 안 가맹점만)
        rng_docs = set(docs) if r.kind in ("region_area", "map5") else None
        pool_rel = [g for d, g in judged.items() if d in c.index and (
            d in rng_docs if rng_docs is not None else
            float(haversine_km(float(r.latitude), float(r.longitude), np.array([c.at[d, "latitude"]]),
                               np.array([c.at[d, "longitude"]]))[0]) <= MAX_KM)]
        answerable = any(g >= BINARY for g in pool_rel)
        base = {"query_id": r.query_id, "kind": r.kind, "bundle": r.bundle, "intent": r.intent, "answerable": answerable}
        if r.kind in ("region_area", "map5"):
            shown = list(docs[rel_shown])
            out = {**base, "N": 0, "order": "sim", "expanded": False, "n_shown": len(shown), "none": not shown,
                   "precision": (float(np.mean([judged.get(d, 0) >= BINARY for d in shown if d in judged]))
                                 if any(d in judged for d in shown) else np.nan),
                   **score_list(shown, judged, [g for g in pool_rel])}
            rows.append(out)
            continue
        within1 = dist <= 1.0 + 1e-9
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
                    if order == "tier":
                        near = set(docs[within1])
                        shown = [d for d in shown if d in near] + [d for d in shown if d not in near]
                pos = {d: i for i, d in enumerate(docs)}
                top3 = [dist[pos[d]] for d in shown[:3]]
                rows.append({**base, "N": n, "order": order, "expanded": expanded, "n_shown": len(shown), "none": not shown,
                             "top3_mean_km": float(np.mean(top3)) if top3 else np.nan,
                             **score_list(shown, judged, pool_rel)})
    per = pd.DataFrame(rows)
    per["false_none"] = per["answerable"] & per["none"]
    OUT.mkdir(parents=True, exist_ok=True)
    per.to_csv(OUT / f"per_request_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    ans = per[per["answerable"]]
    summary = (per.groupby(["kind", "N", "order"]).agg(requests=("query_id", "size"), expanded=("expanded", "mean"),
                                                        false_none=("false_none", "mean"), mean_shown=("n_shown", "mean"),
                                                        top3_km=("top3_mean_km", "mean"))
               .join(ans.groupby(["kind", "N", "order"])[["nDCG@10", "bad@3", "top1_ok", "Judged@10"]].mean())
               .join(per.groupby(["kind", "N", "order"])["precision"].mean() if "precision" in per else None)
               .reset_index())
    summary.to_csv(OUT / f"summary_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 250)
    logger.info("%s (τ = %.2f):\n%s", args.split, tau, summary.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
