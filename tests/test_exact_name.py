import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eval_service_pipeline import BRAND_MIN, exact_name_sort


def test_exact_name_goes_top_even_if_not_candidate():
    corpus = pd.DataFrame({"doc_id": ["a", "b", "c", "d"], "store_name": ["희랑", "희랑카페", "(주)희랑", "다른집"],
                           "latitude": [37.0, 37.0, 37.001, 37.0], "longitude": [127.0, 127.0, 127.0, 127.3]})
    inst = pd.DataFrame({"instance_id": ["i1", "i2"], "latitude": [37.0, 37.0], "longitude": [127.0, 127.0]})
    parsed = pd.DataFrame({"instance_id": ["i1", "i2"], "intent": ["name", "category"], "name_key": ["희랑", "희랑"]})
    run = pd.DataFrame({"query_id": ["i1", "i1", "i2"], "doc_id": ["b", "d", "b"], "score": [1.2, 0.9, 1.0]})
    out = exact_name_sort(run, inst, parsed, corpus, 10.0, "x")
    i1 = out[out["query_id"] == "i1"].sort_values("rank")
    assert list(i1["doc_id"][:2]) == ["a", "c"]                  # 완전 일치(괄호·㈜ 정규화 포함)가 맨 위, 가까운 순
    assert (i1.set_index("doc_id").loc[["a", "c"], "score"] >= BRAND_MIN).all()
    assert i1.set_index("doc_id").at["b", "score"] < BRAND_MIN   # '희랑카페'는 부분 일치라 그대로
    assert set(out[out["query_id"] == "i2"]["doc_id"]) == {"b"}  # 업종 쿼리는 그대로
