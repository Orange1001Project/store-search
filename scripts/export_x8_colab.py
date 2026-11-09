"""X8 Colab 입력(docs/SERVICE_PIPELINE_PLAN.md 11-16) — 상황·추상 쿼리 실패를 겨냥한 두 실험의 입력을 한 번에 내보낸다.

dev 실패 분석(11-16): 1km bad@3 실패의 대부분이 상황·추상 쿼리('보양식 재료', '학용품 파는 곳', '텃밭 농기구', '건강한 음식') — 쿼리에서
가게 종류를 추론해야 하는데 1단계(임베딩 + 문자 BM25)가 놓친다.
  ① reranker(cross-encoder)를 관련성 판단·재정렬 특성으로: 점수가 없는 (쿼리, 가게) 쌍만 Qwen3-Reranker-0.6B로 채점
     → colab/rerank_scores.ipynb(SPLIT = "service_x8")
  ② LLM 쿼리 확장: 쿼리마다 찾는 가게 종류 키워드(취급품목에 쓰이는 말)를 생성(Query2doc, Wang et al. EMNLP 2023; HyDE, Gao et al. ACL 2023)
     → colab/query_expansion.ipynb

대상 쌍: dev·test 모든 사례의 1단계(11-8 구성) 반경 2km 후보(반경마다 상위 50) + X2·X3 요청 후보(1단계 유사도순, 범위 안 상위 50).
출력: colab_upload/x8/rerank_pairs.csv(query_id, doc_id, query, doc_text — 쿼리 단위), colab_upload/x8/expand_queries.csv(query_id, query)
→ Drive `store-search-ai/stack_eval/service_x8/rerank_pairs.csv`, `store-search-ai/query_expansion/expand_queries.csv`
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_x23_round import (
    clean_runs,
    load_corpus,
    load_requests,
    load_runs_x23,
    policy_runs,
)
from eval_service_pipeline import (
    DOC_TEXT_COLUMN,
    RERANK_DIR,
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
    load_bundle_overrides,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.query.aliases import BrandAliases
from store_search_ai.retrieval.fusion import boost

logger = logging.getLogger(__name__)
OUT = Path("colab_upload/x8")
DEPTH = 50


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config("configs/query/service_queryset_v1.yaml")
    bench = load_config("configs/benchmark/storesearch_ko_v1.yaml")
    bdir = Path(cfg["judging"]["benchmark_dir"])
    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    inst = apply_eval_bundle(inst, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    corpus = load_corpus(bench)
    coords = corpus[["doc_id", "latitude", "longitude"]]
    names = corpus.set_index("doc_id")["store_name"]
    runs = load_runs(bdir)
    parsed = parsed_queries(inst, bench["corpus_path"])
    aliases = BrandAliases.load()
    v1 = runs[V1][runs[V1]["query_id"].isin(inst["instance_id"])]
    bm25 = runs["char_bm25"][runs["char_bm25"]["query_id"].isin(inst["instance_id"])]
    union = union_v1(v1, bm25)
    st = boost(union, alias_name_hits(union, dict(zip(parsed["instance_id"], parsed["name_key"], strict=True)), names, aliases),
               0.5, "s")
    st = brand_distance_sort(st, inst, parsed, corpus, aliases, 2.0, "s")
    r = attach_distance(st.rename(columns={"query_id": "instance_id"}), inst, coords)
    frames = []
    for radius in (1.0, 2.0):
        x = r[r["dist_km"] <= radius].sort_values(["instance_id", "rank"]).groupby("instance_id").head(DEPTH)
        frames.append(x.merge(inst[["instance_id", "query_id", "query"]], on="instance_id")[["query_id", "doc_id", "query"]])

    req = load_requests(cfg)
    raw, stale, _ = clean_runs(load_runs_x23(bdir, req), req, corpus, bdir)
    req_ok = req[~req["query_id"].isin(stale)]
    sim = policy_runs(raw[raw["query_id"].isin(req_ok["query_id"])], req_ok, corpus)["sim"]
    top = sim.sort_values(["query_id", "rank"]).groupby("query_id").head(DEPTH)
    top = top.rename(columns={"query_id": "request_id"}).merge(
        req_ok[["query_id", "base_query_id", "query"]].rename(columns={"query_id": "request_id"}), on="request_id")
    frames.append(top.rename(columns={"base_query_id": "query_id"})[["query_id", "doc_id", "query"]])

    pairs = pd.concat(frames, ignore_index=True).drop_duplicates(["query_id", "doc_id"])
    have = set()
    for p in RERANK_DIR.glob("rerank_scores_Qwen3-Reranker-0.6B*.csv"):
        s = pd.read_csv(p, encoding="utf-8-sig")
        have |= set(zip(s["query_id"], s["doc_id"], strict=True))
    todo = pairs[[(q, d) not in have for q, d in zip(pairs["query_id"], pairs["doc_id"], strict=True)]]
    text = corpus.set_index("doc_id")[DOC_TEXT_COLUMN]
    todo = todo.assign(doc_text=todo["doc_id"].map(text))
    OUT.mkdir(parents=True, exist_ok=True)
    todo[["query_id", "doc_id", "query", "doc_text"]].to_csv(OUT / "rerank_pairs.csv", index=False, encoding="utf-8-sig",
                                                            lineterminator="\n")
    queries = inst[["query_id", "query"]].drop_duplicates("query_id").sort_values("query_id")
    queries.to_csv(OUT / "expand_queries.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("후보 쌍 %d개 중 점수 없는 %d개(쿼리 %d개) → %s, 확장할 쿼리 %d개", len(pairs), len(todo), todo["query_id"].nunique(),
                OUT, len(queries))


if __name__ == "__main__":
    main()
