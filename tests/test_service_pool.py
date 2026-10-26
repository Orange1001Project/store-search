import numpy as np
import pandas as pd

from store_search_ai.data.service_pool import (
    annotation_sheet,
    assign_annotators,
    candidates_within,
    double_annotation_queries,
    haversine_km,
    keyword_run,
    lexical_query,
    pool_pairs,
    query_keywords,
    top_k_run,
)


def test_haversine_one_degree_latitude_is_about_111km():
    assert abs(haversine_km(37.0, 127.0, np.array([38.0]), np.array([127.0]))[0] - 111.2) < 0.5


def test_candidates_within_radius_shares_work_by_location():
    corpus = pd.DataFrame({"latitude": [37.5, 37.505, 37.6], "longitude": [127.0, 127.0, 127.0]})
    queries = pd.DataFrame({"query_id": ["q1", "q2"], "latitude": [37.5, 37.5], "longitude": [127.0, 127.0]})
    out = candidates_within(queries, corpus, 1.0)
    assert out["q1"].tolist() == [0, 1] and out["q1"] is out["q2"]


def test_query_keywords_drops_function_words():
    assert query_keywords("떡볶이 파는 곳") == ["떡볶이"]
    assert query_keywords("CGV 영화 예매") == ["CGV", "영화", "예매"]


def test_keyword_run_ranks_by_matched_words_within_candidates():
    texts = np.array(["신세계약국 의약품", "신세계 백화점", "행복약국 의약품", "신세계컴퓨터"])
    doc_ids = np.array(["d0", "d1", "d2", "d3"])
    run = keyword_run("q", "신세계 백화점", np.array([0, 1, 2]), texts, doc_ids, 10)
    assert run["doc_id"].tolist() == ["d1", "d0"]           # 반경 밖 d3 제외, 두 단어 겹친 d1이 먼저


def test_pool_pairs_merges_systems_up_to_depth():
    runs = pd.DataFrame({"query_id": ["q"] * 4, "doc_id": ["a", "b", "a", "c"], "rank": [1, 2, 1, 2],
                         "score": [1, 0.5, 1, 0.5], "system": ["bm25", "bm25", "dense", "dense"]})
    out = pool_pairs(runs, 1).set_index("doc_id")
    assert list(out.index) == ["a"] and out.loc["a", "pool_sources"] == "bm25|dense"


def test_annotation_sheet_hides_systems_and_is_shuffled_deterministically():
    pairs = pd.DataFrame({"query_id": ["q1"] * 5, "doc_id": [f"d{i}" for i in range(5)], "pool_sources": "bm25"})
    queries = pd.DataFrame({"query_id": ["q1"], "query": ["떡집"], "bundle": ["A"], "intent": ["떡집"]})
    corpus = pd.DataFrame({"doc_id": [f"d{i}" for i in range(5)], "store_name": list("abcde"), "item_text": ["떡"] * 5,
                           "market_name": ["m"] * 5})
    a = annotation_sheet(pairs, queries, corpus, 1)
    assert "pool_sources" not in a.columns and "rank" not in a.columns
    assert a.equals(annotation_sheet(pairs, queries, corpus, 1))
    assert a["judgment_id"].is_unique


def test_double_annotation_queries_share():
    ids = [f"q{i}" for i in range(100)]
    chosen = double_annotation_queries(ids, 0.2, 3)
    assert len(chosen) == 20 and chosen == double_annotation_queries(ids, 0.2, 3)


def test_lexical_query_drops_function_words_and_region():
    assert lexical_query("술안주 파는 곳") == "술안주"
    assert lexical_query("뚝섬 식당", "뚝섬") == "식당"
    assert lexical_query("파는 곳") == "파는 곳"            # 남는 단어가 없으면 원래 쿼리


def test_annotation_sheet_keeps_each_query_contiguous():
    pairs = pd.DataFrame({"query_id": ["q1", "q2"] * 5, "doc_id": [f"d{i}" for i in range(10)], "pool_sources": "x"})
    queries = pd.DataFrame({"query_id": ["q1", "q2"], "query": ["a", "b"], "bundle": ["A", "A"], "intent": ["", ""]})
    corpus = pd.DataFrame({"doc_id": [f"d{i}" for i in range(10)], "store_name": "s", "item_text": "", "market_name": "m"})
    order = annotation_sheet(pairs, queries, corpus, 3)["query_id"].tolist()
    assert order == sorted(order, key=order.index) and order.count(order[0]) == 5 and order[:5] == [order[0]] * 5


def test_assign_annotators_balances_and_avoids_own_queries():
    sizes = pd.Series({"q1": 30, "q2": 20, "q3": 10, "q4": 10, "q5": 5})
    writers = {"q1": {"W1"}, "q2": {"W2"}, "q3": {"W1", "W2"}}
    out = assign_annotators(sizes, {"q5"}, {"A": "W1", "B": "W2"}, writers, 0)
    assert "q5" in out["A"] and "q5" in out["B"]                  # 이중 판정은 둘 다
    assert "q1" in out["B"] and "q2" in out["A"]                  # 자기 쿼리는 상대에게
    assert (out["A"] - {"q5"}).isdisjoint(out["B"] - {"q5"})      # 나머지는 한 명만
    assert set().union(*out.values()) == set(sizes.index)


def test_top_k_run_keeps_top_depth_inside_each_radius():
    cand = np.arange(6)
    scores = np.array([0.9, 0.8, 0.7, 0.6, 0.5, 0.4])
    dist = np.array([1.5, 1.5, 0.5, 1.5, 0.5, 0.5])         # 1km 안은 2·4·5번(점수 3·5·6위)
    ids = np.array([f"d{i}" for i in range(6)])
    plain = top_k_run("q", cand, scores, ids, 2, "s")
    assert plain["doc_id"].tolist() == ["d0", "d1"]           # 2km 상위 2개만 — 1km 순위가 비어 버림
    both = top_k_run("q", cand, scores, ids, 2, "s", dist, [1.0, 2.0])
    assert both["doc_id"].tolist() == ["d0", "d1", "d2", "d4"] and both["rank"].tolist() == [1, 2, 3, 4]
