"""지명을 뺀 임베딩 쿼리(2026-11-09, test 정성 점검 1번) — Colab 입력을 만든다.

문자 BM25는 지명을 빼고 검색하는데(service_pool.lexical_query), 임베딩은 쿼리 전체를 인코딩해서 '세종 모두의 미술학원' → 세종종합공구,
'고암 디저트' → 투다리 고암점처럼 상호에 지명이 든 가게를 끌어왔다(test 지명 요청 204개 중 31개). 지명 범위는 이미 반경·필터로
정해지므로 임베딩 쿼리에서도 같은 규칙(service_pool.dense_query)으로 지명을 뺀다.

쿼리 문장이 바뀌는 사례·요청만 다시 돈다:
  colab_upload/service_eval_nr     사례(1km 단계 평가, 반경 1·2km 상위 50) → run 폴더 runs_nr
  colab_upload/service_eval_x23nr  x23 요청(10km·지역 필터·1km 단계)        → run 폴더 runs_x23nr
  colab_upload/p2_cosine_nr        기존 후보 쌍(이전 v1 run·BM25·확장 후보)의 새 문장 코사인 → pair_cosine_<모델>_nr.csv
                                   (query_id = 'nr:' + 새 문장 — 같은 기준 쿼리라도 사례·요청의 지명 해석이 다를 수 있어 문장 단위)
    python scripts/export_noregion.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_x23_round import MAX_KM, load_corpus, load_requests
from eval_service_pipeline import DOC_TEXT_COLUMN, V1, load_pair_cosine

from store_search_ai.data.service_pool import dense_query, filter_mask, haversine_km
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)
UP = Path("colab_upload")


def docs_near(corpus: pd.DataFrame, frame: pd.DataFrame, km: float) -> np.ndarray:
    lat, lon = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float)
    codes = corpus["legal_dong_code"].astype(str).to_numpy()
    keep = np.zeros(len(corpus), dtype=bool)
    for r in frame.itertuples():
        m = filter_mask(getattr(r, "code_prefix", ""), getattr(r, "bbox", ""), codes, lat, lon)
        keep |= m if m is not None else haversine_km(float(r.latitude), float(r.longitude), lat, lon) <= km + 1e-6
    return keep


def write_set(name: str, queries: pd.DataFrame, docs: pd.DataFrame, meta: dict) -> None:
    d = UP / name
    d.mkdir(parents=True, exist_ok=True)
    queries.to_csv(d / "queries.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    docs.to_csv(d / "docs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (d / "meta.json").write_text(json.dumps({**meta, "docs": len(docs), "queries": len(queries)}, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    logger.info("%s: 쿼리 %d개, 가맹점 %d곳", d, len(queries), len(docs))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config("configs/query/service_queryset_v1.yaml")
    bench = load_config("configs/benchmark/storesearch_ko_v1.yaml")
    bdir = Path(cfg["judging"]["benchmark_dir"])
    corpus = load_corpus(bench)
    text = pd.read_parquet(bench["corpus_path"], columns=["doc_id", DOC_TEXT_COLUMN]).set_index("doc_id")[DOC_TEXT_COLUMN]
    corpus = corpus.assign(text=corpus["doc_id"].map(text))
    doc_cols = ["doc_id", "text", "latitude", "longitude", "legal_dong_code"]
    common = {"run_depth": 50, "doc_text": DOC_TEXT_COLUMN, "corpus_path": bench["corpus_path"], "dense_query": "service_pool.dense_query"}

    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    inst["nr"] = [dense_query(q, r) for q, r in zip(inst["query"], inst["region_text"], strict=True)]
    ci = inst[inst["nr"] != inst["query"]]
    write_set("service_eval_nr", ci[["instance_id", "nr", "latitude", "longitude"]].rename(
        columns={"instance_id": "query_id", "nr": "query"}), corpus.loc[docs_near(corpus, ci, 2.0), doc_cols],
        {**common, "judge_radius_km": 2, "report_radii_km": [1, 2], "run_dir": "runs_nr"})

    req = load_requests(cfg)
    req["nr"] = [dense_query(q, r) for q, r in zip(req["query"], req["region_text"], strict=True)]
    cr = req[req["nr"] != req["query"]]
    write_set("service_eval_x23nr", cr[["query_id", "nr", "latitude", "longitude", "code_prefix", "bbox"]].rename(
        columns={"nr": "query"}), corpus.loc[docs_near(corpus, cr, MAX_KM), doc_cols],
        {**common, "judge_radius_km": MAX_KM, "report_radii_km": [1.0, MAX_KM], "run_dir": "runs_x23nr",
         "filters": "code_prefix · bbox — 있으면 반경 대신"})

    # 기존 후보 쌍(기준 쿼리 단위 코사인 사전의 모든 쌍 = 이전 v1 run ∪ BM25 ∪ 확장 후보)을 새 문장으로 다시 잰다
    cos = load_pair_cosine()
    by_base: dict[str, list[str]] = {}
    for q, d in cos:
        by_base.setdefault(q, []).append(d)
    changed = pd.concat([ci[["query_id", "nr"]], cr[["base_query_id", "nr"]].rename(columns={"base_query_id": "query_id"})])
    pairs = pd.DataFrame([("nr:" + t, d) for b, t in changed.drop_duplicates().itertuples(index=False) for d in by_base.get(b, [])],
                         columns=["query_id", "doc_id"]).drop_duplicates()
    out = UP / "p2_cosine_nr"
    out.mkdir(parents=True, exist_ok=True)
    pairs.to_csv(out / "pairs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    qs = sorted(pairs["query_id"].unique())
    pd.DataFrame({"query_id": qs, "query": [q[3:] for q in qs]}).to_csv(out / "queries.csv", index=False, encoding="utf-8-sig",
                                                                         lineterminator="\n")
    text.loc[sorted(pairs["doc_id"].unique())].rename("text").rename_axis("doc_id").reset_index().to_csv(
        out / "docs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (out / "meta.json").write_text(json.dumps({"model": V1, "doc_text": DOC_TEXT_COLUMN, "pairs": len(pairs), "queries": len(qs),
                                               "docs": int(pairs["doc_id"].nunique()), "output_suffix": "_nr"},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("%s: 쌍 %d개, 문장 %d개", out, len(pairs), len(qs))


if __name__ == "__main__":
    main()
