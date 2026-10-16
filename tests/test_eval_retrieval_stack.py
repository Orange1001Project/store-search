import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from eval_retrieval_stack import rerank, rrf_fuse, service_metrics


def _run(system, rows):
    return pd.DataFrame([{"query_id": q, "doc_id": d, "rank": r, "score": 1.0 / r, "system": system} for q, d, r in rows])


def test_rrf_fuse_sums_reciprocal_ranks_and_breaks_ties_by_doc_id():
    dense = _run("dense", [("q1", "a", 1), ("q1", "b", 2), ("q1", "c", 3)])
    bm25 = _run("bm25", [("q1", "c", 1), ("q1", "b", 2)])
    fused = rrf_fuse([dense, bm25], "hyb", k=60, top_k=10)
    # b: 1/62 + 1/62, c: 1/63 + 1/61, a: 1/61 → b ≈ c > a; c(0.03227) > b(0.03226)
    assert fused["doc_id"].tolist() == ["c", "b", "a"]
    assert fused["rank"].tolist() == [1, 2, 3] and set(fused["system"]) == {"hyb"}
    tie = rrf_fuse([_run("x", [("q1", "z", 1)]), _run("y", [("q1", "y", 1)])], "t")
    assert tie["doc_id"].tolist() == ["y", "z"]                      # 같은 점수면 doc_id 순(실행마다 같은 결과)


def test_rerank_reorders_only_head_and_keeps_tail_order():
    run = _run("base", [("q1", "a", 1), ("q1", "b", 2), ("q1", "c", 3), ("q1", "d", 4)])
    scores = {("q1", "a"): 0.1, ("q1", "b"): 0.9, ("q1", "c"): 0.5}
    out = rerank(run, scores, depth=3, system="rr")
    assert out["doc_id"].tolist() == ["b", "c", "a", "d"]            # 상위 3개만 다시 정렬, d는 그대로 뒤
    assert out["rank"].tolist() == [1, 2, 3, 4] and out["score"].is_monotonic_decreasing


def test_service_metrics_counts_wrong_or_unjudged_in_top3():
    run = _run("m", [("q1", "a", 1), ("q1", "x", 2), ("q2", "b", 1), ("q2", "c", 2)])
    rel = {("q1", "a"): 3, ("q2", "b"): 3, ("q2", "c"): 2}
    out = service_metrics(run, rel, pd.Series({"q1": "T1 정확표기", "q2": "T2 동의어"}, name="query_type"))
    assert out["bad@3"] == 0.5 and out["bad@3_n"] == 1 and out["top1_ok"] == 1.0


def test_colab_rerank_notebook_uses_the_same_scoring_function():
    import ast
    import inspect
    import json

    from eval_retrieval_stack import load_reranker

    cells = json.loads((REPO_ROOT / "colab" / "rerank_scores.ipynb").read_text(encoding="utf-8"))["cells"]
    code = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
    reranker_cell = next(c for c in code if c.startswith("# @cell reranker"))
    assert reranker_cell.split("\n", 1)[1] == inspect.getsource(load_reranker).rstrip("\n")   # 로컬과 같은 채점
    for source in code:
        ast.parse(source)
