import numpy as np
import pandas as pd

from store_search_ai.data.service_instances import (
    build_instances,
    intent_words,
    strip_josa,
)
from store_search_ai.data.service_qrels import (
    adjudication_sheet,
    apply_adjudication,
    build_qrels,
    merge_judgments,
)
from store_search_ai.evaluation.service_eval import instance_qrels, paired, score_system


def _sheet(rel, ids):
    return pd.DataFrame({"judgment_id": ids, "query_id": "q", "query": "떡집", "bundle": "A", "intent_hint": "",
                         "doc_id": [f"d{i}" for i in ids], "store_name": "s", "item_text": "", "market_name": "m",
                         "relevance": rel, "annotator_note": np.nan})


def test_merge_rules_lower_grade_binary_split_and_blank():
    a = _sheet([3, 0, 1, np.nan, 2], [1, 2, 3, 4, 5])
    b = _sheet([2, 1, 3, 2], [1, 2, 3, 4])
    m = merge_judgments({"A": a, "B": b}).set_index("judgment_id")
    assert m.loc[1, "provisional"] == 2          # 같은 쪽(2·3) → 낮은 점수
    assert m.loc[2, "provisional"] == 0          # 같은 쪽(0·1) → 낮은 점수
    assert m.loc[3, "reason"] == "이진 판정이 다름"
    assert m.loc[4, "provisional"] == 2          # 한 명 빈칸 → 다른 사람 점수
    assert m.loc[5, "provisional"] == 2          # 혼자 판정
    adj = adjudication_sheet(m.reset_index())
    assert adj["judgment_id"].tolist() == [3]
    final = apply_adjudication(m.reset_index(), pd.DataFrame({"judgment_id": [3], "final_relevance": [3]}))
    q = build_qrels(final)
    assert len(q) == 5 and q.set_index("doc_id").loc["d3", "relevance"] == 3


def test_strip_josa_and_intent_words():
    assert strip_josa("태권도를") == "태권도" and strip_josa("가게") == "가게"
    assert intent_words("태권도를 배울 수 있는 곳") == ["태권도", "배울"]


def _corpus():
    # 쿼리 위치(37.5, 127.0) 근처에는 떡집이 없고, 멀리(35.1, 129.0)에 떡집과 이웃 가게가 있다
    return pd.DataFrame({"doc_id": ["a", "b", "c", "d"], "store_name": ["미용실", "행복떡집", "옆집상회", "교촌치킨 부산점"],
                         "item_text": ["미용", "떡", "잡화", "치킨"], "latitude": [37.5, 35.1, 35.101, 35.2],
                         "longitude": [127.0, 129.0, 129.0, 129.1]})


def _queries():
    return pd.DataFrame({"query_id": ["q1", "q2", "q3"], "query": ["떡 사는 곳", "교촌", "미용실"], "bundle": ["A", "B", "A"],
                         "intent": ["떡집", "교촌치킨", "미용실"], "location_source": ["auto_store", "market", "auto_store"],
                         "latitude": [37.5, 37.5, 37.5], "longitude": [127.0, 127.0, 127.0]})


def test_build_instances_anchors_only_unanswered_queries_near_matching_store():
    qrels = pd.DataFrame({"query_id": ["q3"], "doc_id": ["a"], "relevance": [3]})
    inst = build_instances(_queries(), qrels, _corpus(), {"교촌": ["교촌", "교촌치킨"]}, radius_km=1.0,
                           anchor_keywords={"떡 사는 곳": "떡"}).set_index("instance_id")
    assert "q3@a" not in inst.index                       # 1km 안 정답이 있음 → 앵커 없음
    assert inst.loc["q1@a", "anchor_doc_id"] == "b"       # 지정한 앵커 단어 '떡'(취급품목)
    assert inst.loc["q1@a", "anchor_rule"] == "keyword"
    assert inst.loc["q2@a", "anchor_doc_id"] == "d"       # 브랜드 상호
    near = inst.loc["q1@a"]
    assert abs(near["latitude"] - 35.1) < 0.01            # 앵커 1km 안 가게 좌표


def test_score_system_uses_radius_and_skips_no_answer_instances():
    corpus = pd.DataFrame({"doc_id": ["x", "y", "z"], "latitude": [37.5, 37.505, 37.53], "longitude": [127.0, 127.0, 127.0]})
    instances = pd.DataFrame({"instance_id": ["q1", "q2"], "query_id": ["q1", "q2"], "latitude": [37.5, 37.5],
                              "longitude": [127.0, 127.0]})
    qrels = pd.DataFrame({"query_id": ["q1", "q1", "q1", "q2"], "doc_id": ["x", "y", "z", "x"], "relevance": [0, 3, 3, 0]})
    run = pd.DataFrame({"query_id": ["q1", "q1", "q1", "q2"], "doc_id": ["z", "x", "y", "x"], "rank": [1, 2, 3, 1],
                        "score": [3, 2, 1, 1], "system": "m"})
    iq = instance_qrels(instances, qrels, corpus)
    s1 = score_system(run, iq, instances, corpus, 1.0).set_index("instance_id")
    assert list(s1.index) == ["q1"]                       # q2는 정답 없음 → 제외
    # 1km 안: x(0점) 1위, y(3점) 2위. z(3.3km)는 빠진다 → 이상적 순위는 y 하나
    assert s1.loc["q1", "top1_ok"] == 0 and s1.loc["q1", "bad@3"] == 0 and s1.loc["q1", "n_relevant"] == 1
    assert 0.6 < s1.loc["q1", "nDCG@10"] < 0.65           # 1/log2(3)
    s5 = score_system(run, iq, instances, corpus, 5.0).set_index("instance_id")
    assert s5.loc["q1", "top1_ok"] == 1


def test_paired_reports_delta_and_counts():
    out = paired(pd.Series([0.9, 0.8, 0.7]), pd.Series([0.5, 0.8, 0.9]))
    assert round(out["delta"], 3) == 0.067 and out["wins"] == 1 and out["losses"] == 1 and out["n"] == 3
