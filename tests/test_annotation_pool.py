import pandas as pd
import pytest

from store_search_ai.data.annotation_pool import (
    accumulate_random_candidates,
    accumulate_run_candidates,
    accumulate_targeted_candidates,
    add_candidate,
    build_pool_frame,
    build_pool_stats,
    item_parts,
    load_existing_candidates,
    load_pooling_runs,
    merge_pool_history,
    normalize,
    precompute_match_index,
    source_dict,
    split_terms,
    targeted_match_mask,
)


def test_normalize_casefolds_and_strips_whitespace():
    assert normalize("Chicken 치킨") == "chicken치킨"
    assert normalize(None) == ""
    assert normalize(float("nan")) == ""


def test_split_terms_splits_on_pipe_and_strips():
    assert split_terms("치킨 | 통닭 |") == ["치킨", "통닭"]
    assert split_terms(None) == []


def test_item_parts_splits_on_comma_with_optional_spaces():
    assert item_parts("치킨, 통닭 ,  닭강정") == ["치킨", "통닭", "닭강정"]
    assert item_parts(None) == []


def test_source_dict_parses_json_and_handles_blank():
    assert source_dict('{"a": 1}') == {"a": 1}
    assert source_dict(None) == {}
    assert source_dict("") == {}


def _corpus():
    return pd.DataFrame(
        {
            "doc_id": ["d1", "d2", "d3"],
            "store_name": ["치킨나라", "생닭마트", "빵집"],
            "item_text": ["치킨, 통닭", None, "빵"],
        }
    )


def test_precompute_match_index_normalizes_item_parts_and_store_names():
    item_parts_list, store_name_norm = precompute_match_index(_corpus())
    assert item_parts_list[0] == ["치킨", "통닭"]
    assert item_parts_list[1] == []  # item_text missing
    assert store_name_norm[1] == "생닭마트"


def test_targeted_match_mask_matches_item_parts_first():
    item_parts_list, store_name_norm = precompute_match_index(_corpus())
    mask = targeted_match_mask(item_parts_list, store_name_norm, "치킨")
    assert list(mask) == [True, False, False]


def test_targeted_match_mask_falls_back_to_store_name_when_item_missing():
    item_parts_list, store_name_norm = precompute_match_index(_corpus())
    mask = targeted_match_mask(item_parts_list, store_name_norm, "생닭")
    assert mask[1] == True


def test_add_candidate_merges_sources_for_same_key():
    candidates = {}
    add_candidate(candidates, "q1", "d1", "run:sysA", {"rank": 1}, "round1")
    add_candidate(candidates, "q1", "d1", "run:sysB", {"rank": 2}, "round1")
    assert candidates[("q1", "d1")]["pool_sources"] == {"run:sysA": {"rank": 1}, "run:sysB": {"rank": 2}}
    assert candidates[("q1", "d1")]["first_seen_round"] == "round1"


def test_load_pooling_runs_filters_by_run_depth_and_concatenates(tmp_path):
    pd.DataFrame(
        [{"query_id": "q1", "doc_id": "d1", "rank": 1, "score": 0.9, "system": "sysA"},
         {"query_id": "q1", "doc_id": "d2", "rank": 41, "score": 0.1, "system": "sysA"}]
    ).to_csv(tmp_path / "sysA.csv", index=False)
    pd.DataFrame(
        [{"query_id": "q1", "doc_id": "d3", "rank": 1, "score": 0.8, "system": "sysB"}]
    ).to_csv(tmp_path / "sysB.csv", index=False)

    run_df = load_pooling_runs(tmp_path, run_depth=40)
    assert len(run_df) == 2  # rank=41 row excluded
    assert set(run_df["system"]) == {"sysA", "sysB"}


def test_load_pooling_runs_raises_when_no_csv_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_pooling_runs(tmp_path, run_depth=40)


def test_load_existing_candidates_returns_empty_when_no_file(tmp_path):
    assert load_existing_candidates(tmp_path / "missing.csv") == {}


def test_load_existing_candidates_reconstructs_pool_sources(tmp_path):
    path = tmp_path / "pool.csv"
    pd.DataFrame(
        [{"query_id": "q1", "doc_id": "d1", "pool_sources_json": '{"run:sysA": {"rank": 1}}',
          "first_seen_round": "round1"}]
    ).to_csv(path, index=False)

    candidates = load_existing_candidates(path)
    assert candidates[("q1", "d1")]["pool_sources"] == {"run:sysA": {"rank": 1}}
    assert candidates[("q1", "d1")]["first_seen_round"] == "round1"


def test_accumulate_run_candidates_adds_run_source():
    candidates = {}
    run_df = pd.DataFrame([{"query_id": "q1", "doc_id": "d1", "rank": 1, "score": 0.5, "system": "sysA"}])
    accumulate_run_candidates(candidates, run_df, "round1")
    assert candidates[("q1", "d1")]["pool_sources"]["run:sysA"] == {"rank": 1, "score": 0.5}


def test_accumulate_targeted_candidates_limits_per_term():
    candidates = {}
    corpus = pd.DataFrame(
        {"doc_id": ["d1", "d2", "d3"], "store_name": ["a", "b", "c"], "item_text": ["치킨", "치킨", "치킨"]}
    )
    queries = pd.DataFrame(
        [{"query_id": "q1", "pool_positive_terms": "치킨", "pool_boundary_terms": None}]
    )
    item_parts_list, store_name_norm = precompute_match_index(corpus)
    accumulate_targeted_candidates(candidates, queries, corpus, item_parts_list, store_name_norm, targeted_per_term=2, round_name="r1")
    matched_docs = {doc_id for (qid, doc_id) in candidates if qid == "q1"}
    assert len(matched_docs) == 2  # limited to targeted_per_term=2 of 3 matches


def test_accumulate_random_candidates_is_deterministic_and_excludes_existing():
    corpus = pd.DataFrame({"doc_id": [f"d{i}" for i in range(20)]})
    queries = pd.DataFrame([{"query_id": "q1"}])

    candidates_a = {("q1", "d0"): {"pool_sources": {}}}
    accumulate_random_candidates(candidates_a, queries, corpus, base_seed=42, random_per_query=3, round_name="r1")
    picked_a = {doc_id for (qid, doc_id) in candidates_a if qid == "q1" and doc_id != "d0"}

    candidates_b = {("q1", "d0"): {"pool_sources": {}}}
    accumulate_random_candidates(candidates_b, queries, corpus, base_seed=42, random_per_query=3, round_name="r1")
    picked_b = {doc_id for (qid, doc_id) in candidates_b if qid == "q1" and doc_id != "d0"}

    assert picked_a == picked_b
    assert "d0" not in picked_a  # already-present doc excluded from random sampling
    assert len(picked_a) == 3


def test_build_pool_frame_skips_inactive_queries_and_raises_on_unknown_doc():
    queries = pd.DataFrame([{"query_id": "q1", "query": "치킨", "split": "train", "query_family": "치킨"}])
    corpus = pd.DataFrame([{"doc_id": "d1", "store_name": "s", "item_text": "i", "market_name": "", "market_type": "", "source_region": "서울"}])

    candidates = {
        ("q1", "d1"): {"pool_sources": {"run:sysA": {"rank": 1}}, "first_seen_round": "r1"},
        ("q_inactive", "d1"): {"pool_sources": {}, "first_seen_round": "r1"},
    }
    pool = build_pool_frame(candidates, queries, corpus, "r1")
    assert list(pool["query_id"]) == ["q1"]
    assert pool.iloc[0]["best_run_rank"] == 1

    candidates_bad = {("q1", "d_missing"): {"pool_sources": {}, "first_seen_round": "r1"}}
    with pytest.raises(ValueError, match="not in corpus"):
        build_pool_frame(candidates_bad, queries, corpus, "r1")


def test_build_pool_stats_schema():
    pool = pd.DataFrame(
        [
            {"query_id": "q1", "first_seen_round": "r1"},
            {"query_id": "q1", "first_seen_round": "r0"},
            {"query_id": "q2", "first_seen_round": "r1"},
        ]
    )
    run_df = pd.DataFrame({"system": ["sysB", "sysA", "sysA"]})
    stats = build_pool_stats(pool, run_df, "r1")
    assert stats["round"] == "r1"
    assert stats["pool_rows"] == 3
    assert stats["queries"] == 2
    assert stats["pool_systems"] == ["sysA", "sysB"]
    assert stats["first_seen_in_this_round"] == 2


def test_merge_pool_history_replaces_same_round_keeps_others():
    existing = pd.DataFrame([{"round": "r0", "pool_rows": 10}, {"round": "r1", "pool_rows": 20}])
    merged = merge_pool_history(existing, {"round": "r1", "pool_rows": 99}, "r1")
    assert merged.set_index("round")["pool_rows"].to_dict() == {"r0": 10, "r1": 99}


def test_merge_pool_history_with_no_existing_history_returns_single_row():
    merged = merge_pool_history(None, {"round": "r1", "pool_rows": 5}, "r1")
    assert len(merged) == 1
