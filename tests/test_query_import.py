import random

import pandas as pd
import pytest

from store_search_ai.data.query_import import (
    apply_reclassification,
    assign_fresh_splits,
    build_intent_definition,
    build_query_families,
    has_batchim,
    infer_slug_family_map,
    parse_corrections,
)


def test_has_batchim():
    assert has_batchim("치킨") is True   # 킨: 받침 ㄴ
    assert has_batchim("카페") is False  # 페: 받침 없음
    assert has_batchim("A") is False     # 한글이 아니면 False


def test_build_intent_definition_picks_josa_by_batchim():
    assert build_intent_definition("치킨", "음식점") == "음식점 중 '치킨'을 판매·제공하는 매장"
    assert build_intent_definition("카페", "음식점") == "음식점 중 '카페'를 판매·제공하는 매장"


def test_infer_slug_family_map_excludes_ambiguous_and_multi_family_slugs():
    queries = pd.DataFrame(
        {
            "원본유형": ["chicken/exact", "chicken/synonym", "pork_cutlet/exact", "pork_cutlet/synonym", "bad_row"],
            "패밀리": ["치킨", "치킨", "돈가스_양식", "돈가스_일식", "무관"],
        }
    )
    result = infer_slug_family_map(queries, ambiguous_slugs={"pork_cutlet"})
    assert result == {"chicken": "치킨"}


def test_infer_slug_family_map_excludes_slug_split_across_families():
    queries = pd.DataFrame(
        {
            "원본유형": ["mixed/exact", "mixed/synonym"],
            "패밀리": ["A", "B"],
        }
    )
    assert infer_slug_family_map(queries, ambiguous_slugs=set()) == {}


def test_assign_fresh_splits_covers_every_family_exactly_once():
    families_by_category = {"식품": ["a", "b", "c", "d", "e"], "생활": ["f", "g"]}
    rng = random.Random(42)
    result = assign_fresh_splits(families_by_category, train_ratio=0.42, val_ratio=0.22, rng=rng)
    assert set(result) == {"a", "b", "c", "d", "e", "f", "g"}
    assert set(result.values()) <= {"train", "val", "test"}


def test_apply_reclassification_reassigns_family():
    queries = pd.DataFrame({"질의": ["기름 넣는 곳", "치킨"], "패밀리": ["식자재", "치킨"]})
    result = apply_reclassification(
        queries, {"기름 넣는 곳": ("주유소", "원본유형=gas_station인데 식자재에 들어감")}
    )
    assert result.set_index("질의")["패밀리"].to_dict() == {"기름 넣는 곳": "주유소", "치킨": "치킨"}


def test_apply_reclassification_raises_on_leftover_unassigned():
    queries = pd.DataFrame({"질의": ["미분류 질의"], "패밀리": ["(미판정)"]})
    with pytest.raises(ValueError, match="미판정"):
        apply_reclassification(queries, reclassify_queries={})


def test_parse_corrections_converts_list_to_dict_and_set():
    raw = {
        "reclassify_queries": [
            {"query": "기름 넣는 곳", "family": "주유소", "reason": "r1"},
        ],
        "ambiguous_slugs": ["pork_cutlet"],
    }
    reclassify_queries, ambiguous_slugs = parse_corrections(raw)
    assert reclassify_queries == {"기름 넣는 곳": ("주유소", "r1")}
    assert ambiguous_slugs == {"pork_cutlet"}


def test_parse_corrections_handles_missing_keys():
    reclassify_queries, ambiguous_slugs = parse_corrections({})
    assert reclassify_queries == {}
    assert ambiguous_slugs == set()


def test_build_query_families_end_to_end_small_example():
    queries = pd.DataFrame(
        {
            "질의": ["치킨", "통닭", "카페"],
            "패밀리": ["치킨", "치킨", "카페"],
            "유형": ["T1 정확표기", "T2 동의어", "T1 정확표기"],
            "함정": ["생닭", None, None],
            "원본유형": ["chicken/exact", "chicken/synonym", "cafe/exact"],
        }
    )
    fam_list = pd.DataFrame({"패밀리": ["치킨", "카페"], "대분류": ["음식점", "카페"]})

    output = build_query_families(
        queries=queries,
        fam_list=fam_list,
        existing_split_by_family={},
        reclassify_queries={},
        ambiguous_slugs=set(),
        random_seed=1,
        query_set_version="query_set_test",
        train_ratio=0.5,
        val_ratio=0.5,
    )

    assert output["query_set_version"] == "query_set_test"
    families_by_name = {f["family"]: f for f in output["families"]}
    assert set(families_by_name) == {"치킨", "카페"}
    assert families_by_name["치킨"]["positive_terms"] == ["치킨", "통닭"]
    assert families_by_name["치킨"]["boundary_terms"] == ["생닭"]
    assert len(families_by_name["치킨"]["queries"]) == 2
    assert all(f["split"] in {"train", "val", "test"} for f in output["families"])


def test_build_query_families_inherits_existing_split_over_fresh_assignment():
    queries = pd.DataFrame(
        {
            "질의": ["치킨"],
            "패밀리": ["치킨"],
            "유형": ["T1 정확표기"],
            "함정": [None],
            "원본유형": ["chicken/exact"],
        }
    )
    fam_list = pd.DataFrame({"패밀리": ["치킨"], "대분류": ["음식점"]})

    output = build_query_families(
        queries=queries,
        fam_list=fam_list,
        existing_split_by_family={"치킨": "val"},
        reclassify_queries={},
        ambiguous_slugs=set(),
        random_seed=1,
        query_set_version="query_set_test",
    )

    assert output["families"][0]["split"] == "val"
