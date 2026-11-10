"""P2(a) Colab 입력 — 1단계 후보 중 v1 코사인이 없는 (쿼리, 가맹점) 쌍(docs/archive/SERVICE_PIPELINE_PLAN.md 11-21).

평가 run에는 임베딩 상위 50개 점수만 있어서, 문자 BM25나 LLM 쿼리 확장으로만 들어온 후보는 v1 점수를 0(정규화 최솟값)으로 뒀다.
서비스는 메모리 임베딩으로 모든 후보의 실제 코사인을 계산한다 — 상호가 정확히 맞는데 임베딩 상위 50 밖인 가게('정선 새아네그릇',
'문경 라망화장품', '희랑 원주' — 넓은 지역 모드에서 BM25 1위인데 관련 확률이 낮아 0건)가 이 차이로 빠졌다.

대상 쌍(코사인은 쿼리 문장과 가맹점 문서만으로 정해져 위치와 무관 — 기준 쿼리 ID 단위):
  사례(dev·test 모든 사례, 반경 1·2km): 문자 BM25 run의 가맹점 ∪ 업종 의도 사례의 확장 상위(expansion.DEPTH) − v1 run에 이미 있는 것
  x23 요청(756개): 같은 방식(10km 또는 필터 범위 + 1km 단계)
출력: colab_upload/p2_cosine/{pairs,queries,docs}.csv → Drive store-search-ai/p2_cosine/ → colab/pair_cosine.ipynb
      → pair_cosine_<모델>.csv(query_id, doc_id, cosine)를 results/service_pipeline/p2/에
"""

from __future__ import annotations

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
)
from eval_service_pipeline import DOC_TEXT_COLUMN, V1, load_runs, parsed_queries

from store_search_ai.data.service_pool import candidates_filtered, haversine_km
from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    load_bundle_overrides,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.query.understanding import QueryUnderstanding, load_gazetteer
from store_search_ai.retrieval.expansion import (
    SparseBM25,
    expansion_frame,
    load_expansions,
)
from store_search_ai.retrieval.lexical import build_pool_document_texts

logger = logging.getLogger(__name__)
OUT = Path("colab_upload/p2_cosine")
LLM = "Qwen2.5-14B-Instruct"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config("configs/query/service_queryset_v1.yaml")
    bench = load_config("configs/benchmark/storesearch_ko_v1.yaml")
    bdir = Path(cfg["judging"]["benchmark_dir"])
    corpus = load_corpus(bench)
    doc_ids = corpus["doc_id"].to_numpy()
    lat, lon = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float)
    texts = load_expansions(Path("results/service_pipeline/x8") / f"expansions_{LLM}.csv")
    bm25 = SparseBM25(build_pool_document_texts(corpus))
    pairs: list[pd.DataFrame] = []

    # 1) 사례(1km 평가)
    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    inst = apply_eval_bundle(inst, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    runs = load_runs(bdir)
    base = inst.set_index("instance_id")["query_id"]
    have = runs[V1][["query_id", "doc_id"]].assign(query_id=lambda d: d["query_id"].map(base))
    lex = runs["char_bm25"][["query_id", "doc_id"]].assign(query_id=lambda d: d["query_id"].map(base))
    pairs.append(lex)
    parsed = parsed_queries(inst, bench["corpus_path"])
    cat = inst[inst["instance_id"].isin(parsed.loc[parsed["intent"] == "category", "instance_id"])]
    for r in cat.itertuples():
        d = haversine_km(float(r.latitude), float(r.longitude), lat, lon)
        for radius in cfg["judging"]["report_radii_km"]:
            f = expansion_frame(r.query_id, texts.get(r.query_id, ""), bm25, np.flatnonzero(d <= radius), doc_ids)
            if f is not None:
                pairs.append(f[["query_id", "doc_id"]])
    logger.info("사례 %d개(업종 의도 %d개) 처리", len(inst), len(cat))

    # 2) x23 요청(10km·지역·지도 + 1km 단계)
    req = load_requests(cfg)
    raw, _, _ = clean_runs(load_runs_x23(bdir, req), req, corpus, bdir)
    to_base = dict(zip(req["query_id"], req["base_query_id"], strict=True))
    have = pd.concat([have, raw.loc[raw["system"] == DENSE, ["query_id", "doc_id"]].assign(
        query_id=lambda d: d["query_id"].map(to_base))], ignore_index=True)
    pairs.append(raw.loc[raw["system"] == "char_bm25", ["query_id", "doc_id"]].assign(query_id=lambda d: d["query_id"].map(to_base)))
    qu = QueryUnderstanding(corpus, gazetteer=load_gazetteer())
    cat_req = req[[qu.parse(r.query, float(r.latitude), float(r.longitude)).intent == "category" for r in req.itertuples()]]
    for km in (MAX_KM, 1.0):
        sub = cat_req if km == MAX_KM else cat_req[cat_req["kind"].isin(["expand", "region_point"])]
        cands = candidates_filtered(sub if km == MAX_KM else sub.assign(code_prefix="", bbox=""), corpus, km)
        for r in sub.itertuples():
            f = expansion_frame(r.base_query_id, texts.get(r.base_query_id, ""), bm25, cands[r.query_id], doc_ids)
            if f is not None:
                pairs.append(f[["query_id", "doc_id"]])
    logger.info("x23 요청 %d개(업종 의도 %d개) 처리", len(req), len(cat_req))

    allp = pd.concat(pairs, ignore_index=True).drop_duplicates()
    have = set(zip(have["query_id"], have["doc_id"], strict=True))
    todo = allp[[(q, d) not in have for q, d in zip(allp["query_id"], allp["doc_id"], strict=True)]].reset_index(drop=True)
    OUT.mkdir(parents=True, exist_ok=True)
    todo.to_csv(OUT / "pairs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    qtext = inst.drop_duplicates("query_id").set_index("query_id")["query"]
    qtext.loc[sorted(todo["query_id"].unique())].rename_axis("query_id").reset_index().to_csv(
        OUT / "queries.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    full = pd.read_parquet(bench["corpus_path"], columns=["doc_id", DOC_TEXT_COLUMN]).set_index("doc_id")[DOC_TEXT_COLUMN]
    full.loc[sorted(todo["doc_id"].unique())].rename("text").rename_axis("doc_id").reset_index().to_csv(
        OUT / "docs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    meta = {"model": V1, "doc_text": DOC_TEXT_COLUMN, "pairs": len(todo), "queries": int(todo["query_id"].nunique()),
            "docs": int(todo["doc_id"].nunique()), "expansion_llm": LLM}
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("코사인 없는 쌍 %d개(쿼리 %d개, 가맹점 %d곳) → %s", len(todo), meta["queries"], meta["docs"], OUT)


if __name__ == "__main__":
    main()
