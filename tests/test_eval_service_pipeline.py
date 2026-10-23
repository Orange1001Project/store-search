import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from eval_service_pipeline import RERANK_DEPTH, rerank_variants  # noqa: E402


def test_rerank_reorders_head_only_and_keeps_tail_in_first_stage_order():
    n = RERANK_DEPTH + 2
    docs = [f"d{i}" for i in range(1, n + 1)]
    stage = pd.DataFrame({"query_id": "i1", "doc_id": docs, "rank": range(1, n + 1),
                          "score": [1 - i / n for i in range(n)], "system": "s"})
    instances = pd.DataFrame({"instance_id": ["i1"], "query_id": ["q1"], "query": ["떡집"], "region_text": [""]})
    # reranker는 1단계 순서를 뒤집는다 — 상위 k개 안에서만
    scores = {"m": pd.DataFrame({"query_id": "q1", "doc_id": docs, "score": range(n)})}
    out = rerank_variants(stage, scores, instances, pd.Series(dtype=str))

    k20 = out["rr m k=20"].sort_values("rank")["doc_id"].tolist()
    assert k20[:20] == docs[:20][::-1]          # 상위 20개는 reranker 순서
    assert k20[20:] == docs[20:]                # 나머지는 1단계 순서 그대로 뒤에
    full = out[f"rr m k={RERANK_DEPTH}"].sort_values("rank")["doc_id"].tolist()
    assert full[:RERANK_DEPTH] == docs[:RERANK_DEPTH][::-1] and full[RERANK_DEPTH:] == docs[RERANK_DEPTH:]
    assert f"rr m k={RERANK_DEPTH} mix a=0.5" in out and out["v1+name b=0.5"] is stage
