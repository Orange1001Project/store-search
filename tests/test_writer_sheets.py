import pandas as pd
import pytest

from store_search_ai.data.writer_sheets import (
    WRITER_COLUMNS,
    assign_cards,
    deal,
    part1_rows,
    part2_rows,
    pick_industries,
)

WRITERS = ["W1", "W2", "W3", "W4", "W5", "W6"]


def test_assign_cards_gives_each_card_to_distinct_writers():
    cards = [f"C{i:03d}" for i in range(45)]
    out = assign_cards(cards, WRITERS, overlap=3, seed=1)
    assert sum(len(v) for v in out.values()) == 135
    for card in cards:
        assert sum(card in v for v in out.values()) == 3
    assert all(len(v) == len(set(v)) for v in out.values())   # 한 사람이 같은 카드를 두 번 받지 않음
    assert assign_cards(cards, WRITERS, overlap=3, seed=1) == out


def test_assign_cards_rejects_overlap_above_writer_count():
    with pytest.raises(ValueError):
        assign_cards(["C001"], ["W1", "W2"], overlap=3, seed=0)


def test_deal_is_disjoint_and_checks_supply():
    out = deal(list(range(30)), WRITERS, per_writer=5, seed=0)
    flat = [x for v in out.values() for x in v]
    assert len(flat) == len(set(flat)) == 30
    with pytest.raises(ValueError):
        deal(list(range(10)), WRITERS, per_writer=5, seed=0)


def test_pick_industries_prefers_first_occurrence_and_flags_missing():
    cand = pd.DataFrame({"후보ID": ["A001", "A038", "A050"], "구분": ["미채택", "미포함", "미포함"],
                         "업종·품목": ["태권도", "태권도", "곱창"]})
    out = pick_industries(cand, ["곱창", "태권도"])
    assert out["후보ID"].tolist() == ["A050", "A001"]
    with pytest.raises(ValueError):
        pick_industries(cand, ["없는업종"])


def test_rows_prefill_material_and_location():
    cards = pd.DataFrame({"카드ID": ["C001"], "상황": ["구두 뒤축이 다 닳았다"]})
    p1 = part1_rows("W1", cards, e_count=2)
    assert p1.columns.tolist() == WRITER_COLUMNS
    assert p1["묶음"].tolist() == ["C", "E", "E"]
    assert p1.loc[0, "재료"] == "구두 뒤축이 다 닳았다"
    industries = pd.DataFrame({"후보ID": ["A001"], "업종·품목": ["보청기"]})
    markets = pd.DataFrame({"시장ID": ["M001"], "시도": ["서울특별시"], "시군구": ["마포구"], "시장명": ["망원시장"],
                            "주요품목": ["떡"]})
    p2 = part2_rows("W1", industries, markets, per_industry=5)
    assert (p2["묶음"] == "A").sum() == 5
    d = p2[p2["묶음"] == "D"].iloc[0]
    assert d["가정위치ID"] == "M001" and "망원시장" in d["재료"]
    assert (p2["작성방식"] == "직접").all()
