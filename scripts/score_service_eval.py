"""서비스셋 채점: 시스템 × 반경(1km·2km) × split × 묶음 × 맥락(random·anchor). 규칙은
src/store_search_ai/evaluation/service_eval.py 머리말.

입력: <benchmark_dir>/instances.csv, qrels.csv, runs/(random 사례), runs_anchor/(anchor 사례), 코퍼스 좌표
출력: results/service_eval/
  summary.csv      시스템·반경·split·묶음·맥락별 사례 수, 정답 없는 사례 수, nDCG@10(95% CI), Judged@10, bad@3, top1_ok
  pairs.csv        기준 시스템(설정 judging.dense_models 첫째 = v1) 대비 다른 시스템의 nDCG@10 차이·CI·p (같은 사례끼리)
  per_instance.csv 사례별 지표

사용법:
    python scripts/score_service_eval.py                 # split: dev+test 전체와 test만 둘 다
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.evaluation.service_eval import instance_qrels, paired, score_system
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)
SYSTEMS_EXCLUDED = {"keyword"}   # 키워드 후보는 pool 채널이지 검색 시스템이 아니다


def ci(values: pd.Series, samples: int = 10_000, seed: int = 20261021) -> tuple[float, float]:
    v = values.to_numpy(float)
    if len(v) == 0:
        return (np.nan, np.nan)
    boot = np.random.default_rng(seed).choice(v, size=(samples, len(v)), replace=True).mean(axis=1)
    return float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--out", default="results/service_eval")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    jcfg = cfg["judging"]
    bdir = Path(jcfg["benchmark_dir"])
    bench = load_config(args.benchmark_config)
    instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    queries = pd.read_csv(bdir / "queries.csv", encoding="utf-8-sig", keep_default_na=False).set_index("query_id")
    instances["attribute"] = instances["query_id"].map(queries["attribute"]).fillna("")
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]
    iq = instance_qrels(instances, qrels, coords)

    runs: dict[str, list[pd.DataFrame]] = {}
    for run_dir in (bdir / "runs", bdir / "runs_anchor", bdir / "runs_extra", bdir / "runs_extra_b"):
        for path in sorted(run_dir.glob("*.csv")) if run_dir.exists() else []:
            if path.stem not in SYSTEMS_EXCLUDED:
                runs.setdefault(path.stem, []).append(pd.read_csv(path, encoding="utf-8-sig"))
    baseline = load_config(jcfg["dense_models"][0])["name"]

    per = []
    for system, frames in runs.items():
        run = pd.concat(frames, ignore_index=True)
        for radius in jcfg["report_radii_km"]:
            s = score_system(run, iq, instances, coords, radius)
            per.append(s.assign(system=system, radius_km=radius))
    per = pd.concat(per, ignore_index=True).merge(
        instances[["instance_id", "query_id", "query", "bundle", "split", "context", "attribute"]], on="instance_id")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    per.to_csv(out / "per_instance.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    rows, pair_rows = [], []
    scopes = {"all": ["dev", "test"], "test": ["test"]}
    for scope, splits in scopes.items():
        inst_scope = instances[instances["split"].isin(splits)]
        for radius in jcfg["report_radii_km"]:
            for group_name, keys in (("전체", []), ("묶음", ["bundle"]), ("묶음×맥락", ["bundle", "context"]),
                                     ("속성 쿼리", ["attribute"])):
                p = per[(per["radius_km"] == radius) & per["split"].isin(splits)]
                if group_name == "속성 쿼리":
                    p = p.assign(attribute=np.where(p["attribute"] != "", "속성 있음", "속성 없음"))
                groups = p.groupby(["system", *keys]) if keys else p.groupby(["system"])
                for gkey, g in groups:
                    gkey = gkey if isinstance(gkey, tuple) else (gkey,)
                    label = dict(zip(["system", *keys], gkey, strict=True))
                    lo, hi = ci(g["nDCG@10"])
                    total = inst_scope
                    for k in keys:
                        if k == "attribute":
                            continue
                        total = total[total[k] == label[k]]
                    rows.append({"scope": scope, "radius_km": radius, "group": group_name, **label,
                                 "instances": len(g), "no_answer_instances": len(total) - len(g) if group_name != "속성 쿼리" else None,
                                 "nDCG@10": g["nDCG@10"].mean(), "ci_low": lo, "ci_high": hi,
                                 "Judged@10": g["Judged@10"].mean(), "bad@3": g["bad@3"].mean(), "top1_ok": g["top1_ok"].mean()})
                    if label["system"] != baseline:
                        base = per[(per["system"] == baseline) & (per["radius_km"] == radius)].set_index("instance_id")["nDCG@10"]
                        mine = g.set_index("instance_id")["nDCG@10"]
                        pair_rows.append({"scope": scope, "radius_km": radius, "group": group_name, **label,
                                          "baseline": baseline, **paired(base.reindex(mine.index), mine)})
    summary = pd.DataFrame(rows)
    summary.to_csv(out / "summary.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.DataFrame(pair_rows).to_csv(out / "pairs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 220)
    view = summary[(summary["group"] == "묶음") & (summary["scope"] == "test")]
    logger.info("test, 묶음별:\n%s", view[["radius_km", "system", "bundle", "instances", "no_answer_instances", "nDCG@10",
                                          "ci_low", "ci_high", "Judged@10", "bad@3", "top1_ok"]].round(3).to_string(index=False))
    logger.info("저장: %s", out)


if __name__ == "__main__":
    main()
