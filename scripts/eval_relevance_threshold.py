"""X1 관련 임계값(docs/SERVICE_PIPELINE_PLAN.md 11-4) — 1단계(v1+name(qu) b=0.5) 점수를 P(관련)로 보정하고 임계값을 dev에서 고른다.

판정 없이 기존 qrels로 한다. test는 X7에서 한 번만 본다(이 스크립트는 dev 전용).

1) 후보: 사례마다 반경(1km·2km) 안 1단계 결과(반경마다 상위 50 — run 깊이). 특성 = 점수, 그 사례 1위와의 점수 차, log(반경 안 순위).
2) 보정 비교(쿼리 단위 5겹 교차검증, 의도 묶음 name/category마다 따로): isotonic(점수만) vs 로지스틱(점수+차이+순위)
   vs 로지스틱(+문자 BM25). 모델은 1km log-loss로 고른다.
3) 임계값 곡선: P ≥ p인 가게만 보여 줄 때 사례 결과 — 헛된 "없음"(정답이 있는데 아무것도 안 보임), 놓침(보여 준 것 중 정답 없음),
   정답 없는 사례에 노출, 노출 정밀도(판정된 것 기준 / 미판정 = 오답), k개 이상 보이는 비율(반경 확장 빈도 추정 — N=1·3·5·10).
   임계값은 헛된 "없음" ≤ 5%를 지키는 것 중 노출 정밀도가 가장 높은 p(2026-11-04 — 처음 제안한 '정밀도 ≥ 0.9'는 데이터 없이
   정한 값이었고 dev에서 헛된 "없음" ≤ 5%와 함께 맞출 수 없었다).
4) 고른 모델을 dev 전체로 다시 학습해 계수·임계값을 저장 → configs/service/search_policy_v1.yaml relevance에 옮긴다.

    python scripts/eval_relevance_threshold.py            # dev, 모든 사례(--set all이 기본 — 보정 데이터가 많아야 해서)

출력: results/service_pipeline/x1/{calibration,curve,chosen}_dev.csv, per_instance_dev.csv, calibrator.json
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
from eval_service_pipeline import first_stage, load_runs

from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    attach_distance,
    instance_qrels,
    load_bundle_overrides,
)
from store_search_ai.evaluation.threshold import (
    BINARY,
    FEATURE_SETS,
    add_features,
    calibration_metrics,
    fit,
    instance_outcomes,
    predict,
    summarize_outcomes,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.query.understanding import (
    QueryUnderstanding,
    load_gazetteer,
)

logger = logging.getLogger(__name__)
OUT = Path("results/service_pipeline/x1")
KINDS = ("isotonic", "logistic", "logistic_bm25")
GRID = np.round(np.arange(0.10, 0.951, 0.05), 2)
FOLDS = 5
SEED = 20261104
TARGET_HIDDEN = 0.05     # 헛된 "없음"(정답이 있는데 아무것도 안 보임) 상한 — 이 안에서 노출 정밀도가 가장 높은 임계값


def parse_instances(instances: pd.DataFrame, corpus_path: str) -> pd.DataFrame:
    """사례마다 쿼리 이해 결과(의도·상호 일치 키) — 사용자 위치 = 사례 위치."""

    corpus = pd.read_parquet(corpus_path, columns=["store_name", "item_text", "address", "market_name", "source_region",
                                                   "legal_dong_code", "latitude", "longitude", "geo_status"])
    qu = QueryUnderstanding(corpus[corpus["geo_status"] == "VALID"], gazetteer=load_gazetteer())
    rows = []
    for i, q, la, lo in zip(instances["instance_id"], instances["query"], instances["latitude"], instances["longitude"],
                            strict=True):
        p = qu.parse(q, float(la), float(lo))
        rows.append({"instance_id": i, "intent": p.intent, "name_key": p.name_key,
                     "group": "name" if p.intent in ("name", "brand") else "category"})
    return pd.DataFrame(rows)


def candidates(stage: pd.DataFrame, instances: pd.DataFrame, coords: pd.DataFrame, qrels: pd.DataFrame,
               parsed: pd.DataFrame, radius: float, bm25: pd.DataFrame) -> pd.DataFrame:
    r = attach_distance(stage.rename(columns={"query_id": "instance_id"}), instances, coords)
    r = r[r["dist_km"] <= radius][["instance_id", "doc_id", "score", "dist_km"]].merge(bm25, on=["instance_id", "doc_id"], how="left")
    r = add_features(r)
    r = r.merge(instances[["instance_id", "query_id", "bundle"]], on="instance_id").merge(parsed[["instance_id", "group"]],
                                                                                          on="instance_id")
    return r.merge(qrels, on=["query_id", "doc_id"], how="left").assign(radius_km=radius)


def oof_predictions(cands: pd.DataFrame, kind: str) -> np.ndarray:
    """쿼리 단위 5겹: 학습 겹의 판정된 쌍으로 맞추고 평가 겹의 모든 후보(미판정 포함)를 예측한다."""

    queries = np.array(sorted(cands["query_id"].unique()))
    fold_of = dict(zip(queries, np.random.default_rng(SEED).permutation(len(queries)) % FOLDS, strict=True))
    f = cands["query_id"].map(fold_of).to_numpy()
    judged = cands["relevance"].notna().to_numpy()
    out = np.full(len(cands), np.nan)
    for k in range(FOLDS):
        for g in cands["group"].unique():
            in_g = (cands["group"] == g).to_numpy()
            train = cands[(f != k) & in_g & judged]
            test = (f == k) & in_g
            if test.any() and (train["relevance"] >= BINARY).nunique() == 2:
                out[test] = predict(fit(kind, train), kind, cands[test])
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["main", "all"], default="all", help="all: dev 모든 사례(기본), main: 주 평가셋 dev만")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    instances = apply_eval_bundle(instances, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    instances = instances[instances["split"] == "dev"]
    main_ids = set(pd.read_csv(cfg["eval_set"]["output"], encoding="utf-8-sig")["instance_id"])
    if args.set == "main":
        instances = instances[instances["instance_id"].isin(main_ids)]
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]
    names = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name"]).set_index("doc_id")["store_name"]
    runs = load_runs(bdir)
    bm25 = (runs["char_bm25"].rename(columns={"query_id": "instance_id", "score": "bm25"})[["instance_id", "doc_id", "bm25"]]
            .drop_duplicates(["instance_id", "doc_id"]))

    parsed = parse_instances(instances, bench["corpus_path"])
    stage = first_stage(runs, instances, names, dict(zip(parsed["instance_id"], parsed["name_key"], strict=True)),
                        "v1+name(qu) b=0.5")
    iq = instance_qrels(instances, qrels, coords)
    OUT.mkdir(parents=True, exist_ok=True)

    calib, curve, per_rows = [], [], []
    for radius in cfg["judging"]["report_radii_km"]:
        cands = candidates(stage, instances, coords, qrels, parsed, radius, bm25)
        answerable = set(iq[(iq["dist_km"] <= radius) & (iq["relevance"] >= BINARY)]["instance_id"])
        judged = cands["relevance"].notna().to_numpy()
        y = (cands["relevance"] >= BINARY).to_numpy(int)
        for kind in KINDS:
            p = oof_predictions(cands, kind)
            for g in ["전체", "name", "category"]:
                m = judged & (True if g == "전체" else (cands["group"] == g).to_numpy())
                calib.append({"radius_km": radius, "model": kind, "group": g, **calibration_metrics(p[m], y[m])})
            c = cands.assign(p=p)
            for t in GRID:
                for subset, ids in [("all", None), ("main", main_ids)]:
                    cc = c if ids is None else c[c["instance_id"].isin(ids)]
                    o = instance_outcomes(cc, answerable, t)
                    curve.append({"radius_km": radius, "model": kind, "threshold": t, "set": subset, **summarize_outcomes(o)})
            per_rows.append(c.assign(model=kind))
    calib = pd.DataFrame(calib)
    curve = pd.DataFrame(curve)
    calib.to_csv(OUT / "calibration_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    curve.to_csv(OUT / "curve_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    # 모델: 1km 전체 log-loss가 낮은 쪽. 임계값: 1km·dev 전체에서 헛된 "없음" ≤ 5%인 것 중 노출 정밀도가 가장 높은 p
    c1 = calib[(calib["radius_km"] == 1) & (calib["group"] == "전체")].set_index("model")
    best = str(c1["log_loss"].idxmin())
    cur = curve[(curve["radius_km"] == 1) & (curve["model"] == best) & (curve["set"] == "all")]
    ok = cur[cur["hidden_rate"] <= TARGET_HIDDEN]
    t_star = float(ok.loc[ok["precision_judged"].idxmax(), "threshold"]) if len(ok) else float(cur["threshold"].min())
    chosen = curve[(curve["model"] == best) & (curve["threshold"] == t_star)]
    chosen.to_csv(OUT / "chosen_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    # 사례별 결과(고른 모델·임계값, 1km)
    per = pd.concat(per_rows)
    per = per[(per["model"] == best) & (per["radius_km"] == 1)]
    ans1 = set(iq[(iq["dist_km"] <= 1) & (iq["relevance"] >= BINARY)]["instance_id"])
    pi = instance_outcomes(per, ans1, t_star).merge(instances[["instance_id", "query", "bundle", "split"]], on="instance_id")
    pi = pi.merge(parsed[["instance_id", "group"]], on="instance_id").assign(main=lambda d: d["instance_id"].isin(main_ids))
    pi.to_csv(OUT / "per_instance_dev.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    # dev 전체로 다시 학습 → 백엔드로 넘길 계수(1km 후보 기준 특성)
    cands1 = candidates(stage, instances, coords, qrels, parsed, 1, bm25)
    calibrator = {"model": best, "threshold_p": t_star, "features": FEATURE_SETS.get(best, ["score"]),
                  "score": "min-max(v1 코사인, 사례 후보 = v1·문자 BM25 상위 합집합 안) + 0.5 × 상호 일치(쿼리 이해 키) — scripts/eval_service_pipeline.py first_stage / fusion.boost",
                  "feature_scope": "반경 안 후보 기준(gap = 점수 − 반경 안 1위 점수, log_rank = log(반경 안 순위), "
                                   "bm25_rel = 문자 BM25 ÷ 반경 안 최댓값, BM25 상위 50 밖이면 0)",
                  "trained_on": f"dev {args.set} 1km judged pairs", "groups": {}}
    for g in ["name", "category"]:
        tr = cands1[(cands1["group"] == g) & cands1["relevance"].notna()]
        m = fit(best, tr)
        if best in FEATURE_SETS:
            calibrator["groups"][g] = {"intercept": float(m.intercept_[0]),
                                       "coef": dict(zip(FEATURE_SETS[best], map(float, m.coef_[0]), strict=True)), "pairs": len(tr)}
        else:
            calibrator["groups"][g] = {"x": list(map(float, m.X_thresholds_)), "y": list(map(float, m.y_thresholds_)),
                                       "pairs": len(tr)}
    (OUT / "calibrator.json").write_text(json.dumps(calibrator, ensure_ascii=False, indent=1), encoding="utf-8")

    pd.set_option("display.width", 250)
    logger.info("보정(1km·2km, 쿼리 5겹 교차검증):\n%s", calib.to_string(index=False))
    view = curve[(curve["radius_km"] == 1) & (curve["set"] == "all")]
    logger.info("임계값 곡선(1km, dev 전체):\n%s", view[["model", "threshold", "hidden_rate", "miss_rate", "false_show_rate",
                                                     "precision_judged", "precision_pessimistic", "judged_share_of_shown",
                                                     "mean_shown", "shown_ge_1", "shown_ge_3", "shown_ge_5",
                                                     "shown_ge_10"]].to_string(index=False))
    logger.info("선택: %s, P ≥ %.2f(헛된 없음 ≤ %.0f%% 중 노출 정밀도 최고)\n%s", best, t_star, TARGET_HIDDEN * 100,
                chosen.to_string(index=False))


if __name__ == "__main__":
    main()
