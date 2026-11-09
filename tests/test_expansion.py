import numpy as np
import pandas as pd

from store_search_ai.retrieval.expansion import (
    SparseBM25,
    add_expansion,
    expansion_frame,
    load_expansions,
)


def test_sparse_bm25_ranks_matching_docs():
    bm = SparseBM25(pd.Series(["정육점 한우 돼지고기", "문구 팬시 필기구", "방앗간 떡 참기름"]))
    s = bm.score("한우 정육", np.arange(3))
    assert s.argmax() == 0 and s[1] == 0


def test_expansion_frame_and_add():
    filler = [f"가게{i} 잡화" for i in range(20)]                # idf가 양수가 되게(한우가 드문 말)
    bm = SparseBM25(pd.Series(["정육점 한우", "문구점", "한우 식당", *filler]))
    f = expansion_frame("q1", "한우", bm, np.array([0, 1, 2]), np.array(["a", "b", "c"]))
    assert set(f["doc_id"]) == {"a", "c"} and f["exp"].max() == 1.0
    stage = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["b", "a"], "score": [1.0, 0.9]})
    out = add_expansion(stage, f, 0.3, "x", brand_min=50.0)
    sc, e = out.set_index("doc_id")["score"], f.set_index("doc_id")["exp"]
    assert np.isclose(sc["a"], 0.9 + 0.3 * e["a"])
    assert np.isclose(sc["c"], 0.9 + 0.3 * e["c"])       # 1단계에 없던 가게는 사례 최솟값(0.9)에서 시작해 후보에 들어감
    assert sc["b"] == 1.0
    assert list(out["rank"]) == [1, 2, 3]


def test_add_expansion_keeps_brand_rows_and_zero_weight():
    stage = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["a", "b"], "score": [99.0, 0.5]})
    exp = pd.DataFrame({"query_id": ["q1"], "doc_id": ["a"], "exp": [1.0], "erank": [1]})
    assert add_expansion(stage, exp, 0.3, "x", 50.0).set_index("doc_id")["score"]["a"] == 99.0
    assert len(add_expansion(stage, exp, 0.0, "x", 50.0)) == 2


def test_load_expansions(tmp_path):
    p = tmp_path / "e.csv"
    pd.DataFrame({"query_id": ["q1", "q2"], "expansion": ["정육, 한우 ,", ""]}).to_csv(p, index=False, encoding="utf-8-sig")
    assert load_expansions(p) == {"q1": "정육 한우", "q2": ""}
