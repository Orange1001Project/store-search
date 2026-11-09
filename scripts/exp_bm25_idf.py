"""1단계 문자 BM25의 IDF 범위 실험(2026-11-09, PR #9 리뷰 8번).

지금 1단계 BM25 run은 '판정 반경 안 가게'(사례 묶음마다 후보 합집합)만으로 색인해 IDF·평균 문서 길이를 계산한다
(build_service_pool.py runs/bm25, build_x23_round.py runs). 서비스에는 판정 반경이 없으므로 전국(좌표 유효 21만 곳) 색인이
맞다 — LLM 확장 BM25(expansion.SparseBM25)와 같은 식(음수 idf는 0)으로 모든 char_bm25 run을 다시 만든다.

run 파일(git 추적)을 제자리에서 덮어쓴다. 평가 뒤 되돌리려면:
    git checkout -- benchmark/service_ko_v1/runs*/char_bm25.csv
사용법:
    python scripts/exp_bm25_idf.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_service_pool import SETS, load_inputs, write_run
from build_x23_round import MAX_KM, RADII, RUN_DIR, load_corpus, load_requests

from store_search_ai.data.service_pool import (
    branch_suffixes,
    candidates_filtered,
    distances_km,
    lexical_query,
    top_k_run,
)
from store_search_ai.pipeline.common import load_config
from store_search_ai.retrieval.expansion import SparseBM25
from store_search_ai.retrieval.lexical import build_pool_document_texts

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config("configs/query/service_queryset_v1.yaml")
    bench = load_config("configs/benchmark/storesearch_ko_v1.yaml")
    jcfg = cfg["judging"]
    bdir = Path(jcfg["benchmark_dir"])
    nat = load_corpus(bench)
    logger.info("전국 문자 BM25 색인: %d곳", len(nat))
    bm25 = SparseBM25(build_pool_document_texts(nat))
    row_of = pd.Series(np.arange(len(nat)), index=nat["doc_id"].to_numpy())
    branch = branch_suffixes(nat)
    depth = jcfg["run_depth"]

    def score(query: str, doc_ids: np.ndarray) -> np.ndarray:
        rows = row_of.reindex(doc_ids).to_numpy()
        if np.isnan(rows).any():
            raise SystemExit("전국 색인에 없는 후보가 있습니다(좌표 무효 가게)")
        return bm25.score(query, rows.astype(int))

    for name, (_, run_dir) in SETS.items():
        queries, corpus, cands = load_inputs(cfg, bench, name)
        doc_ids = corpus["doc_id"].to_numpy()
        radii = sorted(set(jcfg["report_radii_km"]))
        dist = distances_km(queries, corpus, cands)
        frames = [top_k_run(qid, cands[qid], score(lexical_query(q, region, branch), doc_ids[cands[qid]]), doc_ids, depth,
                            "char_bm25", dist[qid], radii)
                  for qid, q, region in zip(queries["query_id"], queries["query"], queries["region_text"], strict=True)]
        write_run(pd.concat(frames, ignore_index=True), bdir / run_dir / "char_bm25.csv")

    req = load_requests(cfg)
    cands = candidates_filtered(req, nat, MAX_KM)
    dist = distances_km(req, nat, cands)
    doc_ids = nat["doc_id"].to_numpy()
    frames = []
    for r in req.itertuples():
        filtered = bool(r.code_prefix or r.bbox)
        c = cands[r.query_id]
        frames.append(top_k_run(r.query_id, c, bm25.score(lexical_query(r.query, r.region_text, branch), c), doc_ids, depth,
                                "char_bm25", None if filtered else dist[r.query_id], None if filtered else RADII))
    write_run(pd.concat(frames, ignore_index=True), bdir / RUN_DIR / "char_bm25.csv")


if __name__ == "__main__":
    main()
