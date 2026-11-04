"""공공데이터 지명 사전을 만든다(src/store_search_ai/data/gazetteer.py, docs/SERVICE_PIPELINE_PLAN.md 11절).

원본(공공데이터, 저장소 밖 — 행정동 경계 shp가 135MB):
  [행정안전부] 행정표준코드 법정동코드 정보.csv, 센서스 공간정보 지역 코드.xlsx, BND_ADM_DONG_PG/(shp·dbf),
  전체_도시철도역사정보_20260630.xlsx, 전국전통시장표준데이터.csv

    python scripts/build_gazetteer.py --src ~/Downloads/store-search-ai/외부공공데이터

출력: data/geo/gazetteer_v1.parquet, data/geo/gazetteer_v1.meta.json(원본 파일 sha256·통계·확인 결과)
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.data.gazetteer import build_gazetteer
from store_search_ai.pipeline.common import sha256_file

logger = logging.getLogger(__name__)
SOURCES = ["[행정안전부] 행정표준코드 법정동코드 정보.csv", "센서스 공간정보 지역 코드.xlsx", "BND_ADM_DONG_PG/BND_ADM_DONG_PG.shp",
           "BND_ADM_DONG_PG/BND_ADM_DONG_PG.dbf", "전체_도시철도역사정보_20260630.xlsx", "전국전통시장표준데이터.csv"]


def check_against_corpus(gaz: pd.DataFrame, corpus_path: str) -> dict:
    """좌표 변환·코드 연결 확인: 시군구 중심과 그 시군구 가맹점 중앙값의 거리(km)."""

    c = pd.read_parquet(corpus_path, columns=["legal_dong_code", "latitude", "longitude", "geo_status"])
    c = c[c["geo_status"] == "VALID"]
    med = c.groupby(c["legal_dong_code"].str[:5])[["latitude", "longitude"]].median()
    sg = gaz[gaz["kind"] == "sigungu"].drop_duplicates("sigungu_code").set_index("sigungu_code")
    j = sg.join(med, how="inner")
    d = np.hypot(j["lat"] - j["latitude"], (j["lon"] - j["longitude"]) * 0.8) * 111
    covered = c["legal_dong_code"].str[:5].isin(set(gaz["sigungu_code"])).mean()
    return {"sigungu_center_vs_store_median_km": {"median": round(float(d.median()), 2), "p90": round(float(d.quantile(0.9)), 2),
                                                  "max": round(float(d.max()), 2), "n": len(d)},
            "corpus_stores_with_known_sigungu": round(float(covered), 4)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default=str(Path.home() / "Downloads" / "store-search-ai" / "외부공공데이터"))
    parser.add_argument("--corpus", default="data/corpus/store_corpus_v002.parquet")
    parser.add_argument("--out", default="data/geo/gazetteer_v1.parquet")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    corpus = pd.read_parquet(args.corpus, columns=["legal_dong_code", "latitude", "longitude", "geo_status"])
    gaz, stats = build_gazetteer(args.src, corpus[corpus["geo_status"] == "VALID"])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    gaz.to_parquet(out, index=False)
    meta = {"sources": {s: sha256_file(Path(args.src) / s) for s in SOURCES}, "stats": stats,
            "check": check_against_corpus(gaz, args.corpus)}
    out.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(json.dumps({"stats": stats, "check": meta["check"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
