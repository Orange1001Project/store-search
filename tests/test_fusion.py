import pandas as pd
import pytest

from store_search_ai.retrieval.fusion import boost, convex, minmax, name_match, normalize_name, rrf


def _run(qid, docs, scores, system="s"):
    return pd.DataFrame({"query_id": qid, "doc_id": docs, "rank": range(1, len(docs) + 1), "score": scores, "system": system})


def test_rrf_sums_reciprocal_ranks_and_reranks():
    a = _run("q", ["d1", "d2"], [0.9, 0.8])
    b = _run("q", ["d2", "d3"], [10, 5])
    out = rrf([a, b], k=10).set_index("doc_id")
    assert out.loc["d2", "rank"] == 1                    # 둘 다에 있음: 1/12 + 1/11
    assert out.loc["d2", "score"] == pytest.approx(1 / 12 + 1 / 11)
    assert out.loc["d1", "rank"] == 2 and out.loc["d3", "rank"] == 3   # 1/11 vs 1/12


def test_minmax_per_query_and_constant_scores():
    r = pd.concat([_run("q1", ["a", "b", "c"], [5, 3, 1]), _run("q2", ["x"], [7])])
    m = minmax(r)
    assert m["score"].tolist() == [1.0, 0.5, 0.0, 0.0]   # q2는 점수가 하나뿐 → 0


def test_convex_missing_doc_counts_as_zero_and_weights_checked():
    a = _run("q", ["d1", "d2"], [1.0, 0.0])
    b = _run("q", ["d2", "d3"], [1.0, 0.0])
    out = convex([a, b], [0.7, 0.3]).set_index("doc_id")["score"]
    assert out["d1"] == pytest.approx(0.7) and out["d2"] == pytest.approx(0.3) and out["d3"] == 0
    with pytest.raises(ValueError):
        convex([a, b], [1.0])


def test_name_match_both_directions_and_min_len():
    assert normalize_name("(주)크린 토피아") == "크린토피아"
    assert name_match("크린토피아", "크린토피아 부평점")      # 쿼리 ⊂ 상호
    assert name_match("통영짱이상회 본점", "짱이상회")          # 상호 ⊂ 쿼리
    assert not name_match("떡", "떡집")                         # 3글자 미만은 신호 없음
    assert not name_match("떡볶이", "김밥")


def test_boost_lifts_hits_above_close_scores():
    r = _run("q", ["d1", "d2", "d3"], [1.0, 0.9, 0.0])
    out = boost(r, pd.Series([False, True, False]), beta=0.5, name="b")
    assert out["doc_id"].tolist() == ["d2", "d1", "d3"]
    assert (out["system"] == "b").all()
