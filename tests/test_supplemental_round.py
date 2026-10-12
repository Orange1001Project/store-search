import pandas as pd
import pytest

from store_search_ai.data.annotation_sheets import build_judgment_id
from store_search_ai.data.supplemental_round import (
    build_supplemental_sheet_rows,
    load_supplement_runs,
    merge_into_base_adjudication,
    new_pair_counts,
    select_new_pairs,
    target_queries_with_terms,
)


def _queries():
    return pd.DataFrame(
        {
            "query_id": ["q1", "q2"],
            "query": ["바지 기장 줄이는 곳", "옷 수선"],
            "intent_definition": ["수선", "수선"],
            "split": ["test", "test"],
            "query_family": ["수선", "수선"],
            "query_type": ["T5", "T1"],
            "pool_positive_terms": [None, None],
            "pool_boundary_terms": ["의류 판매", "의류 판매"],
        }
    )


def test_target_queries_with_terms_only_overrides_selected_queries():
    target = target_queries_with_terms(_queries(), ["q1"], ["수선", "옷수선"])
    assert target["query_id"].tolist() == ["q1"]
    assert target.iloc[0]["pool_positive_terms"] == "수선|옷수선"
    assert target.iloc[0]["pool_boundary_terms"] == ""
    with pytest.raises(ValueError, match="없는 query_id"):
        target_queries_with_terms(_queries(), ["q9"], ["수선"])
    with pytest.raises(ValueError, match="비어"):
        target_queries_with_terms(_queries(), ["q1"], [])


def test_select_new_pairs_keeps_only_this_round_and_unjudged():
    pool = pd.DataFrame(
        {
            "query_id": ["q1", "q1", "q1", "q2"],
            "doc_id": ["d_old", "d_new", "d_judged", "d_new"],
            "first_seen_round": ["lexical_v1", "supplement_v1", "supplement_v1", "supplement_v1"],
        }
    )
    judged = {build_judgment_id("q1", "d_judged")}
    new = select_new_pairs(pool, "supplement_v1", ["q1"], judged)
    assert new["doc_id"].tolist() == ["d_new"]
    assert new.iloc[0]["judgment_id"] == build_judgment_id("q1", "d_new")


def test_build_supplemental_sheet_rows_adds_metadata_and_empty_fields():
    pairs = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "judgment_id": ["j1"]})
    rows = build_supplemental_sheet_rows(pairs, _queries(), "supplement_v1")
    row = rows.iloc[0]
    assert row["query"] == "바지 기장 줄이는 곳" and row["split"] == "test"
    assert row["annotation_round"] == "supplement_v1" and row["relevance"] == ""


def test_merge_appends_new_rows_replaces_same_round_and_protects_base():
    base = pd.DataFrame({"judgment_id": ["a", "b"], "final_relevance": [3, 0]})
    sup = pd.DataFrame({"judgment_id": ["c"], "final_relevance": [2], "supplemental_round": ["supplement_v1"]})

    merged = merge_into_base_adjudication(base, sup)
    assert merged["judgment_id"].tolist() == ["a", "b", "c"]
    assert merged["supplemental_round"].isna().tolist() == [True, True, False]

    # 같은 라운드를 다시 merge하면 그 라운드 행만 교체
    sup2 = pd.DataFrame({"judgment_id": ["c"], "final_relevance": [3], "supplemental_round": ["supplement_v1"]})
    again = merge_into_base_adjudication(merged, sup2)
    assert again["judgment_id"].tolist() == ["a", "b", "c"]
    assert again.loc[again["judgment_id"] == "c", "final_relevance"].item() == 3

    # 원래 판정과 겹치면 에러(기존 판정은 바꾸지 않음)
    clash = pd.DataFrame({"judgment_id": ["a"], "final_relevance": [1], "supplemental_round": ["supplement_v1"]})
    with pytest.raises(ValueError, match="겹칩니다"):
        merge_into_base_adjudication(base, clash)


def test_exclude_supplemental_rows_drops_rounds_with_manifest(tmp_path):
    import json

    from store_search_ai.data.supplemental_round import exclude_supplemental_rows

    pool = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["a", "b"], "first_seen_round": ["lexical_v1", "supplement_v1"]})
    assert len(exclude_supplemental_rows(pool, tmp_path)) == 2  # 보충 라운드 없으면 그대로

    (tmp_path / "supplement_v1").mkdir()
    (tmp_path / "supplement_v1" / "supplemental_manifest.json").write_text(json.dumps({"round": "supplement_v1"}), encoding="utf-8")
    assert exclude_supplemental_rows(pool, tmp_path)["doc_id"].tolist() == ["a"]


def test_exclude_supplemental_rows_keeps_rounds_of_other_base_round(tmp_path):
    import json

    from store_search_ai.data.supplemental_round import exclude_supplemental_rows

    pool = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["a", "b"], "first_seen_round": ["lexical_v1", "supplement_v1"]})
    (tmp_path / "supplement_v1").mkdir()
    (tmp_path / "supplement_v1" / "supplemental_manifest.json").write_text(
        json.dumps({"round": "supplement_v1", "base_round": "full_annotation_v1"}), encoding="utf-8")
    assert exclude_supplemental_rows(pool, tmp_path, "full_annotation_v1")["doc_id"].tolist() == ["a"]
    # 새 본 라운드에는 v1 보충 판정이 합쳐지지 않으므로(11/12번) 보충 후보도 새 시트에 들어가야 한다
    assert exclude_supplemental_rows(pool, tmp_path, "full_annotation_v2")["doc_id"].tolist() == ["a", "b"]


def test_supplemental_adjudication_paths_finds_merged_and_pending_rounds(tmp_path):
    import json

    from store_search_ai.data.supplemental_round import (
        SUPPLEMENTAL_ADJUDICATION_NAME,
        supplemental_adjudication_paths,
    )

    for name, merged in (("supplement_v1", True), ("supplement_v2", False)):
        (tmp_path / name / "analysis").mkdir(parents=True)
        manifest = {"round": name, "base_round": "full_annotation_v1"}
        (tmp_path / name / "supplemental_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if merged:
            (tmp_path / name / "analysis" / SUPPLEMENTAL_ADJUDICATION_NAME).write_text("x", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "supplemental_manifest.json").write_text(
        json.dumps({"round": "other", "base_round": "full_annotation_v2"}), encoding="utf-8"
    )

    paths, pending = supplemental_adjudication_paths(tmp_path, "full_annotation_v1")
    assert [p.parent.parent.name for p in paths] == ["supplement_v1"]
    assert pending == ["supplement_v2"]


def test_combine_with_supplemental_keeps_base_and_rejects_overlap():
    from store_search_ai.data.supplemental_round import combine_with_supplemental

    base = pd.DataFrame({"judgment_id": ["a"], "final_relevance": [3]})
    s1 = pd.DataFrame({"judgment_id": ["b"], "final_relevance": [2], "supplemental_round": ["s1"]})
    s2 = pd.DataFrame({"judgment_id": ["c"], "final_relevance": [0], "supplemental_round": ["s2"]})
    combined = combine_with_supplemental(base, [s1, s2])
    assert combined["judgment_id"].tolist() == ["a", "b", "c"]
    assert base["judgment_id"].tolist() == ["a"]  # 원본은 그대로
    with pytest.raises(ValueError):
        combine_with_supplemental(base, [pd.DataFrame({"judgment_id": ["a"], "supplemental_round": ["s3"]})])


def _write_run(path, system, rows):
    pd.DataFrame(
        [{"query_id": q, "doc_id": d, "rank": r, "score": 1.0 / r, "system": system} for q, d, r in rows]
    ).to_csv(path, index=False, encoding="utf-8-sig")


def test_load_supplement_runs_filters_targets_and_rejects_bad_runs(tmp_path):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    _write_run(runs_dir / "a.csv", "dense_a", [("q1", "d1", 1), ("q1", "d2", 2), ("q1", "d3", 3), ("q9", "d1", 1)])
    runs = load_supplement_runs(runs_dir, 2, {"q1"}, {"char_bm25_v1"})
    assert runs[["query_id", "doc_id"]].values.tolist() == [["q1", "d1"], ["q1", "d2"]]   # 대상 쿼리·depth만

    with pytest.raises(ValueError, match="겹칩니다"):
        load_supplement_runs(runs_dir, 2, {"q1"}, {"dense_a"})
    with pytest.raises(ValueError, match="run에 없습니다"):
        load_supplement_runs(runs_dir, 2, {"q1", "q2"}, set())
    _write_run(runs_dir / "b.csv", "dense_a", [("q1", "d1", 1)])
    with pytest.raises(ValueError, match="두 개 이상"):
        load_supplement_runs(runs_dir, 2, {"q1"}, set())


def test_new_pair_counts_counts_only_unpooled_pairs_per_depth():
    runs = pd.DataFrame(
        {
            "query_id": ["q1"] * 4,
            "doc_id": ["d1", "d2", "d1", "d3"],
            "rank": [1, 2, 1, 2],
            "system": ["a", "a", "b", "b"],
        }
    )
    table = new_pair_counts(runs, {("q1", "d1")}, [1, 2]).set_index("depth")
    assert table.loc[1, "union"] == 0                                   # d1은 이미 pool에 있음
    assert (table.loc[2, "a"], table.loc[2, "b"], table.loc[2, "union"]) == (1, 1, 2)
