import numpy as np
import pandas as pd

from store_search_ai.evaluation.threshold import (
    add_features,
    calibration_metrics,
    fit,
    instance_outcomes,
    predict,
)


def test_features_are_relative_to_each_instance():
    c = add_features(pd.DataFrame({"instance_id": ["a", "a", "b"], "doc_id": ["x", "y", "z"], "score": [0.9, 0.7, 0.5],
                                   "bm25": [4.0, np.nan, 0.0]}))
    a = c[c["instance_id"] == "a"].set_index("doc_id")
    assert a.loc["x", "gap"] == 0 and np.isclose(a.loc["y", "gap"], -0.2)
    assert a.loc["x", "log_rank"] == 0 and np.isclose(a.loc["y", "log_rank"], np.log(2))
    assert a.loc["x", "bm25_rel"] == 1 and a.loc["y", "bm25_rel"] == 0          # BM25 상위에 없으면 0
    assert c.loc[c["instance_id"] == "b", "bm25_rel"].iloc[0] == 0               # 최댓값 0이면 나누지 않음


def test_logistic_calibration_orders_by_score():
    rng = np.random.default_rng(0)
    s = rng.uniform(0, 1, 400)
    frame = add_features(pd.DataFrame({"instance_id": np.arange(400) // 10, "doc_id": np.arange(400), "score": s,
                                       "bm25": 0.0, "relevance": np.where(s > 0.6, 3, 0)}))
    p = predict(fit("logistic_bm25", frame), "logistic_bm25", frame)
    assert p[frame["score"] > 0.8].mean() > 0.8 and p[frame["score"] < 0.3].mean() < 0.2
    m = calibration_metrics(p, (frame["relevance"] >= 2).to_numpy(int))
    assert m["auc"] > 0.95


def test_instance_outcomes_hidden_miss_false_show():
    cands = pd.DataFrame({"instance_id": ["a", "a", "b", "c"], "p": [0.9, 0.1, 0.2, 0.8],
                          "relevance": [3, 0, 3, np.nan]})
    o = instance_outcomes(cands, answerable={"a", "b"}, threshold=0.5).set_index("instance_id")
    assert not o.loc["a", "hidden"] and not o.loc["a", "miss"]                  # 정답을 보여 줌
    assert o.loc["b", "hidden"] and o.loc["b", "miss"]                          # 정답이 있는데 아무것도 안 보임(헛된 없음)
    assert o.loc["c", "false_show"]                                              # 정답 없는 사례에 노출
    assert o.loc["a", "expected_relevant"] == 1.0
