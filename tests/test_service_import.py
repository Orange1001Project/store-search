import pandas as pd

from store_search_ai.data.service_import import (
    assign_locations,
    auto_location,
    build_service_queries,
    detect_region_text,
    merge_duplicates,
    split_groups,
    team_b_rows,
    writer_rows,
)


def _rows(items):
    """(query, bundle, basis, writer[, location]) → writer_rows와 같은 열의 표."""

    out = []
    for item in items:
        query, bundle, basis, writer, *loc = item
        out.append({"query": query, "bundle": bundle, "intent": "", "region_text": "", "location_id": loc[0] if loc else "",
                    "basis_id": basis, "writer": writer, "note": ""})
    return pd.DataFrame(out)


def _markets():
    return pd.DataFrame({"시장ID": ["M001", "M002"], "위도": [37.5, 35.1], "경도": [127.0, 129.0]})


def _points():
    return pd.DataFrame({"doc_id": ["z9", "a1", "m5"], "latitude": [36.0, 37.0, 35.0], "longitude": [127.0, 128.0, 129.0]})


def _stores():
    return pd.DataFrame({"표본ID": ["S001"], "가맹점명": ["대박축산"], "주소": ["서울특별시 중랑구 묵동 1"],
                         "시장명": ["묵동시장"], "위도": [37.6], "경도": [127.08]})


def test_writer_rows_keeps_only_filled_writer_sheets():
    sheet = pd.DataFrame({"작성자": ["W1", "W1"], "묶음": ["C", "E"], "근거ID": ["C001", None], "재료": ["가", None],
                          "질의": ["구두 수선", None], "의도": ["수선집", None], "지역표현": [None, None],
                          "가정위치ID": [None, None], "작성방식": ["직접", "직접"], "비고": [None, None]})
    out = writer_rows({"W1_1부_C_E": sheet, "배정표": pd.DataFrame({"x": [1]})})
    assert out["query"].tolist() == ["구두 수선"]
    assert out.loc[0, "writer"] == "W1" and out.loc[0, "basis_id"] == "C001"


def test_team_b_rows_takes_only_human_b():
    team = pd.DataFrame({"작성자": ["B_개별점포", "A_식생활"], "묶음": ["B", "A"], "질의": ["묵동 대박축산", "식품점"],
                         "의도": ["대박축산", "식료품"], "지역표현": [None, None], "가정위치ID": [None, "M001"],
                         "근거ID": ["S001", "A001"], "작성방식": ["개별 가맹점 표본 기반(독립 표본)", "AI 역할별 업종 초안"],
                         "비고": [None, None]})
    b, draft = team_b_rows(team, ["개별 가맹점 표본 기반(독립 표본)"])
    assert b["query"].tolist() == ["묵동 대박축산"] and b.loc[0, "writer"] == "team:B_개별점포"
    assert draft["질의"].tolist() == ["식품점"]


def test_detect_region_text_uses_address_and_market_not_store_name():
    assert detect_region_text("묵동 대박축산", "대박축산", "서울특별시 중랑구 묵동 1", "묵동시장") == "묵동"
    assert detect_region_text("묵동시장 대박축산", "대박축산", "서울 중랑구", "묵동시장") == "묵동시장"
    assert detect_region_text("대박축산", "대박축산", "서울 중랑구 묵동", "묵동시장") == ""


def test_merge_duplicates_counts_writers_and_prefers_bundle_order():
    rows = _rows([("야식", "A", "A001", "W2"), ("야식", "C", "C022", "W1"), ("야 식", "C", "C022", "W3"),
                  ("화분", "C", "C027", "W1")])
    out = merge_duplicates(rows, ["B", "D", "C", "A", "E"]).set_index("query")
    assert out.loc["야식", "bundle"] == "C"            # C가 A보다 앞
    assert out.loc["야식", "n_writers"] == 3
    assert out.loc["야식", "also_in_bundles"] == "A"
    assert len(out) == 2


def test_split_groups_keeps_same_basis_together_and_is_deterministic():
    rows = _rows([(f"q{i}", "C", f"C{i // 3:03d}", "W1") for i in range(30)])
    queries = merge_duplicates(rows, ["C"])
    a = split_groups(queries, 0.25, seed=7)
    assert a.equals(split_groups(queries, 0.25, seed=7))
    by_basis = pd.DataFrame({"basis": queries["basis_id"], "split": a}).groupby("basis")["split"].nunique()
    assert (by_basis == 1).all()                         # 한 카드의 쿼리는 한쪽에만
    assert 6 <= (a == "dev").sum() <= 9


def test_assign_locations_by_bundle():
    queries = merge_duplicates(_rows([("묵동 대박축산", "B", "S001", "team:x"), ("망원시장 떡집", "D", "M002", "W1", "M002"),
                                      ("화분", "C", "C027", "W1")]), ["B", "D", "C"])
    out = assign_locations(queries, _stores(), _markets(), _points()).set_index("query")
    assert out.loc["묵동 대박축산", "location_source"] == "store" and out.loc["묵동 대박축산", "region_text"] == "묵동"
    assert out.loc["망원시장 떡집", "location_id"] == "M002" and out.loc["망원시장 떡집", "location_source"] == "market"
    assert out.loc["화분", "location_source"] == "auto_store"
    sorted_points = _points().sort_values("doc_id").reset_index(drop=True)
    assert out.loc["화분", "location_id"] == f"doc:{auto_location('화 분', sorted_points)['doc_id']}"   # 공백과 무관
    shuffled = assign_locations(queries, _stores(), _markets(), _points().iloc[::-1]).set_index("query")
    assert shuffled.loc["화분", "location_id"] == out.loc["화분", "location_id"]      # 코퍼스 행 순서와 무관


def test_build_excludes_old_train_and_configured_queries():
    rows = _rows([("반찬가게", "C", "C037", "W1"), ("커튼", "C", "C026", "W1"), ("백화점", "E", "", "W1"),
                  ("화분", "C", "C027", "W2")])
    out = build_service_queries(
        rows, ["C", "E"], {"반찬가게": "train", "커튼": "test"}, [{"query": "백화점", "reason": "가맹점 있음"}],
        _stores(), _markets(), _points(), 0.25, 1,
    ).set_index("query")
    assert out.loc["반찬가게", "status"] == "excluded" and out.loc["반찬가게", "split"] == ""
    assert out.loc["백화점", "exclude_reason"] == "가맹점 있음"
    assert out.loc["커튼", "status"] == "active" and out.loc["커튼", "old_benchmark_split"] == "test"
    assert set(out["query_id"]) == {"sq_C001", "sq_C002", "sq_C003", "sq_E001"}
