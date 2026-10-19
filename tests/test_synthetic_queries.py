import pandas as pd

from store_search_ai.data.synthetic_queries import (
    build_alias_table,
    canon_key,
    fewshot_examples,
    generate_name_queries,
    name_variants,
    paren_names,
    strip_branch,
)

ALIASES = {"GS25": ["GS25", "지에스25", "지에스(GS)25"], "BBQ": ["비비큐", "BBQ"]}


def _corpus() -> pd.DataFrame:
    names = [
        "지에스25 강남점", "GS25역삼점", "지에스(GS)25 서초점", "비비큐 방배점", "형제상회", "형제상회",
        "(주)차이나 웍 짬뽕", "제이스타일(J STYLE)", "카페", "맛집(용봉점)",
    ]
    return pd.DataFrame({"doc_id": [f"d{i}" for i in range(len(names))], "store_name": names})


def test_strip_branch_spaced_and_attached_brand():
    assert strip_branch("크린토피아 운남7단지점", []) == "크린토피아"
    assert strip_branch("GS25역삼점", ["GS25"]) == "GS25"
    assert strip_branch("형제상회", ["GS25"]) == "형제상회"


def test_canon_key_maps_aliases_to_one_key():
    table = build_alias_table(ALIASES)
    assert canon_key("지에스25", table) == canon_key("GS25", table) == canon_key("지에스(GS)25", table)
    assert canon_key("비비큐", table) == canon_key("bbq", table)
    assert canon_key("(주)차이나 웍 짬뽕", table) == "차이나웍짬뽕"


def test_paren_names_skip_branch_digits_and_alias_parts():
    assert paren_names("제이스타일(J STYLE)", []) == ["J STYLE"]
    assert paren_names("맛집(용봉점)", []) == []
    assert paren_names("가게(050)", []) == []
    assert paren_names("지에스(GS)25 서초점", ["지에스(GS)25"]) == []


def test_name_variants_include_space_and_alias_forms():
    variants = {text: kind for kind, text in name_variants("비비큐 방배점", ["비비큐"], ALIASES)}
    assert variants["비비큐 방배점"] == "full"
    assert variants["비비큐"] == "no_branch"
    assert variants["BBQ"] == "alias"
    spaced = {text: kind for kind, text in name_variants("(주)차이나 웍 짬뽕", [], ALIASES)}
    assert spaced["차이나웍짬뽕"] == "no_space"


def test_generate_name_queries_positives_depend_on_query_only():
    out = generate_name_queries(
        _corpus(), n_stores=100, brands=["GS25", "지에스25", "비비큐"], aliases=ALIASES, vocab={"카페"},
        exclude_doc_ids=set(), exclude_brands=[], many_positives=50, seed=0,
    ).set_index("query")
    # 브랜드 쿼리는 표기와 상관없이 세 지점 모두
    assert set(out.loc["GS25", "positive_doc_ids"].split("|")) == {"d0", "d1", "d2"}
    assert out.loc["형제상회", "n_positives"] == 2
    assert "카페" not in out.index           # 업종어와 같은 상호는 상호명 쿼리가 아님
    assert "용봉점" not in out.index


def test_generate_name_queries_drops_queries_touching_excluded_stores():
    out = generate_name_queries(
        _corpus(), n_stores=100, brands=["GS25", "지에스25"], aliases=ALIASES, vocab=set(),
        exclude_doc_ids={"d4"}, exclude_brands=["비비큐"], many_positives=50, seed=0,
    )
    assert "형제상회" not in set(out["query"])
    assert not out["query"].str.contains("비비큐|BBQ").any()


def test_fewshot_examples_respects_split_and_inactive():
    families = [
        {"family": "치킨", "split": "train", "queries": [
            {"type": "T2 동의어", "text": "통닭"}, {"type": "T4 구어·문장", "text": "치킨 먹을 데"},
            {"type": "T6 기계변형", "text": "치킨추천"}]},
        {"family": "치과", "split": "test", "queries": [{"type": "T2 동의어", "text": "치아"}]},
    ]
    out = fewshot_examples(families, inactive_ids={"q_치킨_01"}, split="train")
    assert set(zip(out["bundle"], out["query"])) == {("A", "치킨 먹을 데"), ("C", "치킨 먹을 데")}
