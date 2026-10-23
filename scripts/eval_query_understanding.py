"""쿼리 이해 평가(docs/SERVICE_PIPELINE_PLAN.md 6절) — 서비스셋 쿼리마다 지역·의도를 파싱하고 정답과 비교한다.

정답
  - 지역 문자열: 쿼리의 region_text(D는 작성자가 적음, B는 대상 가게 주소로 자동 추출 — 빠진 것이 있어 참고용).
  - 지역 위치: B 쿼리의 대상 가게(basis_id)와 D 쿼리의 가정 위치가 파싱한 지역 안(가게 집합)·근처에 있는지.
  - 의도: B = 상호·브랜드, A·C·D·E = 업종. A·C·E에서 지역이 잡히면 오탐.
기본은 dev. test는 규칙을 다 고친 뒤 한 번(--split test).

출력: results/query_understanding/parsed_<split>.csv, summary_<split>.csv
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.pipeline.common import load_config
from store_search_ai.query.understanding import QueryUnderstanding

logger = logging.getLogger(__name__)
REMOTE = [(37.5663, 126.9779), (35.1798, 129.0750)]   # 서울시청, 부산시청
CORPUS_COLUMNS = ["doc_id", "store_name", "item_text", "address", "market_name", "source_region", "legal_dong_code",
                  "latitude", "longitude", "geo_status"]


def km(lat1, lon1, lat2, lon2) -> float:
    a, b = np.radians([lat1, lon1]), np.radians([lat2, lon2])
    h = np.sin((b[0] - a[0]) / 2) ** 2 + np.cos(a[0]) * np.cos(b[0]) * np.sin((b[1] - a[1]) / 2) ** 2
    return float(2 * 6371.0 * np.arcsin(np.sqrt(h)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    corpus = pd.read_parquet(bench["corpus_path"], columns=CORPUS_COLUMNS)
    corpus = corpus[corpus["geo_status"] == "VALID"].reset_index(drop=True)
    qu = QueryUnderstanding(corpus)
    lat, lon = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float)
    queries = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    queries = queries[(queries["status"] == "active") & (queries["split"] == args.split)]

    rows = []
    for q in queries.itertuples():
        # 사용자는 쿼리의 가정 위치에 있다고 둔다(같은 이름 여러 곳일 때 가까운 곳을 고르는 데만 쓰임)
        p = qu.parse(q.query, float(q.latitude), float(q.longitude))
        # B 개별 가게 쿼리의 가정 위치 = 대상 가게 좌표(location_source=store) → 그 좌표의 가게(50m 안)를 대상으로 본다
        target = None
        if q.bundle == "B" and q.location_source == "store":
            d = np.hypot(lat - float(q.latitude), (lon - float(q.longitude)) * 0.8) * 111.0
            target = np.flatnonzero(d <= 0.05)
        in_region = (bool(np.isin(target, p.region.doc_idx).any()) if (p.region is not None and target is not None)
                     else None)
        # 원격 사용자: 쿼리 지역과 먼 곳(서울시청, 가정 위치가 서울 근처면 부산시청)에서 같은 쿼리를 검색할 때 지역을 맞게 고르는지
        far = REMOTE[1] if km(float(q.latitude), float(q.longitude), *REMOTE[0]) < 100 else REMOTE[0]
        r = qu.parse(q.query, *far)
        # 맞게 골랐는가 = 지역 가게 집합에 실제 위치(가정 위치 300m 안)의 가게가 들어 있음. 시군구 단위는 중심점이 의미 없어서
        d = np.hypot(lat - float(q.latitude), (lon - float(q.longitude)) * 0.8) * 111.0
        here = np.flatnonzero(d <= 0.3)
        local_ok = bool(np.isin(here, p.region.doc_idx).any()) if p.region else None
        remote_ok = bool(np.isin(here, r.region.doc_idx).any()) if r.region else None
        rows.append({"query_id": q.query_id, "bundle": q.bundle, "query": q.query, "gold_region": q.region_text,
                     "parsed_region": p.region_text, "core": p.core, "intent": p.intent,
                     "region_stores": len(p.region.doc_idx) if p.region else 0,
                     "target_in_region": in_region,
                     "center_km_from_location": (km(*p.region.center, float(q.latitude), float(q.longitude))
                                                 if p.region else np.nan),
                     "region_has_location": local_ok, "remote_region": r.region_text, "remote_region_has_location": remote_ok,
                     "name_hits": len(p.name_doc_idx),
                     "target_in_name_hits": (bool(np.isin(target, p.name_doc_idx).any()) if target is not None else None)})
    out = pd.DataFrame(rows)
    out["region_exact"] = out["parsed_region"] == out["gold_region"]
    summary = []
    for b, g in out.groupby("bundle"):
        has = g["gold_region"] != ""
        summary.append({
            "bundle": b, "queries": len(g),
            "지역 정답 있음": int(has.sum()),
            "지역 일치(정답 있는 쿼리)": round(g.loc[has, "region_exact"].mean(), 3) if has.any() else np.nan,
            "지역 잡음(정답 없는 쿼리)": int((~has & (g["parsed_region"] != "")).sum()),
            "대상 가게가 지역 안(B)": round(g["target_in_region"].dropna().astype(float).mean(), 3)
            if g["target_in_region"].notna().any() else np.nan,
            "지역 중심~가정위치 중앙값 km": round(g["center_km_from_location"].median(), 2),
            "지역이 실제 위치 포함": round(g["region_has_location"].dropna().astype(float).mean(), 3)
            if g["region_has_location"].notna().any() else np.nan,
            "원격 사용자: 지역이 실제 위치 포함": round(g["remote_region_has_location"].dropna().astype(float).mean(), 3)
            if g["remote_region_has_location"].notna().any() else np.nan,
            "의도 name/brand 비율": round(g["intent"].isin(["name", "brand"]).mean(), 3),
            "대상 가게가 상호 후보 안(B)": round(g["target_in_name_hits"].dropna().astype(float).mean(), 3)
            if g["target_in_name_hits"].notna().any() else np.nan,
        })
    summary = pd.DataFrame(summary)
    od = Path("results/query_understanding")
    od.mkdir(parents=True, exist_ok=True)
    out.to_csv(od / f"parsed_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    summary.to_csv(od / f"summary_{args.split}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    pd.set_option("display.width", 250)
    logger.info("%s:\n%s", args.split, summary.to_string(index=False))


if __name__ == "__main__":
    main()
