import pandas as pd
import pytest

from store_search_ai.data.annotation_sheets import (
    VISIBLE_COLUMNS,
    add_empty_annotation_fields,
    add_judgment_ids,
    attach_query_metadata,
    build_annotation_manifest,
    build_annotator_frame,
    build_judgment_id,
    build_split_stats,
    prepare_pool,
    stable_shuffle,
    validate_pool_and_queries,
    write_annotation_file,
)


def _queries():
    return pd.DataFrame(
        [
            {"query_id": "q1", "query": "치킨", "intent_definition": "치킨 파는 곳", "split": "train", "query_family": "치킨", "query_type": "exact", "status": "active"},
            {"query_id": "q2", "query": "카페", "intent_definition": "카페", "split": "val", "query_family": "카페", "query_type": "exact", "status": "active"},
            {"query_id": "q3", "query": "빵집", "intent_definition": "빵집", "split": "test", "query_family": "빵집", "query_type": "exact", "status": "active"},
        ]
    )


def _pool():
    return pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "store_name": "치킨집", "item_text": "치킨", "market_name": "", "market_type": "", "source_region": "서울"},
            {"query_id": "q1", "doc_id": "d2", "store_name": "치킨집2", "item_text": "치킨", "market_name": "", "market_type": "", "source_region": "서울"},
            {"query_id": "q2", "doc_id": "d3", "store_name": "카페1", "item_text": "커피", "market_name": "", "market_type": "", "source_region": "서울"},
            {"query_id": "q3", "doc_id": "d4", "store_name": "빵집1", "item_text": "빵", "market_name": "", "market_type": "", "source_region": "서울"},
        ]
    )


def test_build_judgment_id_is_deterministic_and_order_sensitive():
    assert build_judgment_id("q1", "d1") == build_judgment_id("q1", "d1")
    assert build_judgment_id("q1", "d1") != build_judgment_id("d1", "q1")
    assert len(build_judgment_id("q1", "d1")) == 20


def test_stable_shuffle_is_deterministic_for_a_fixed_seed_and_annotator():
    frame = pd.DataFrame({"query_id": ["q1", "q1", "q1"], "doc_id": ["d1", "d2", "d3"]})
    first = stable_shuffle(frame, seed=1, annotator="A")
    second = stable_shuffle(frame, seed=1, annotator="A")
    assert list(first["doc_id"]) == list(second["doc_id"])


def test_stable_shuffle_differs_between_annotators_for_the_same_seed():
    frame = pd.DataFrame(
        {"query_id": ["q1"] * 8, "doc_id": [f"d{i}" for i in range(8)]}
    )
    a_order = list(stable_shuffle(frame, seed=1, annotator="A")["doc_id"])
    b_order = list(stable_shuffle(frame, seed=1, annotator="B")["doc_id"])
    assert a_order != b_order


def test_write_annotation_file_uses_visible_columns_only(tmp_path):
    frame = pd.DataFrame([{col: "" for col in VISIBLE_COLUMNS} | {"extra": "hidden"}])
    path = tmp_path / "out.csv"
    write_annotation_file(frame, path)
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.split(",") == VISIBLE_COLUMNS


def test_validate_pool_and_queries_rejects_wrong_split_set():
    queries = _queries().copy()
    queries["split"] = "train"  # val/test 없어짐
    with pytest.raises(ValueError, match="train/val/test"):
        validate_pool_and_queries(_pool(), queries)


def test_validate_pool_and_queries_rejects_duplicate_query_id():
    queries = pd.concat([_queries(), _queries().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate query_id"):
        validate_pool_and_queries(_pool(), queries)


def test_validate_pool_and_queries_rejects_duplicate_pool_pair():
    pool = pd.concat([_pool(), _pool().iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="Duplicate query_id/doc_id"):
        validate_pool_and_queries(pool, _queries())


def test_validate_pool_and_queries_rejects_missing_candidates():
    pool = _pool()[_pool()["query_id"] != "q3"]
    with pytest.raises(ValueError, match="without candidates"):
        validate_pool_and_queries(pool, _queries())


def test_attach_query_metadata_fills_columns_from_queries_not_pool():
    pool = attach_query_metadata(_pool(), _queries())
    row = pool[pool["doc_id"] == "d1"].iloc[0]
    assert row["query"] == "치킨"
    assert row["split"] == "train"
    assert row["query_family"] == "치킨"


def test_attach_query_metadata_drops_rows_for_inactive_queries():
    queries = _queries()
    pool = pd.concat(
        [_pool(), pd.DataFrame([{"query_id": "q_inactive", "doc_id": "d9", "store_name": "", "item_text": "", "market_name": "", "market_type": "", "source_region": ""}])],
        ignore_index=True,
    )
    result = attach_query_metadata(pool, queries)
    assert "q_inactive" not in set(result["query_id"])


def test_add_judgment_ids_detects_duplicates():
    pool = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["d1", "d1"]})
    with pytest.raises(ValueError, match="Duplicate judgment_id"):
        add_judgment_ids(pool)


def test_add_empty_annotation_fields_sets_round_and_blanks():
    pool = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"]})
    result = add_empty_annotation_fields(pool, "round_x")
    assert result.iloc[0]["annotation_round"] == "round_x"
    assert result.iloc[0]["relevance"] == ""
    assert result.iloc[0]["uncertain"] == ""
    assert result.iloc[0]["annotator_note"] == ""


def test_prepare_pool_end_to_end_produces_visible_columns():
    pool = prepare_pool(_pool(), _queries(), "full_annotation_v1")
    for col in VISIBLE_COLUMNS:
        if col not in ("annotator", "relevance", "uncertain", "annotator_note"):
            assert col in pool.columns or col in ("relevance", "uncertain", "annotator_note")
    assert pool["judgment_id"].is_unique
    assert (pool["annotation_round"] == "full_annotation_v1").all()


def test_build_annotator_frame_a_includes_all_splits_b_only_val_test():
    pool = prepare_pool(_pool(), _queries(), "r1")
    a = build_annotator_frame(pool, seed=1, annotator="A")
    b = build_annotator_frame(pool, seed=1, annotator="B", splits=["val", "test"])

    assert set(a["split"]) == {"train", "val", "test"}
    assert set(b["split"]) == {"val", "test"}
    assert (a["annotator"] == "A").all()
    assert (b["annotator"] == "B").all()


def test_build_split_stats_reports_candidates_per_query():
    pool = prepare_pool(_pool(), _queries(), "r1")
    stats = build_split_stats(pool)
    train_stats = next(s for s in stats if s["split"] == "train")
    assert train_stats["queries"] == 1
    assert train_stats["judgments"] == 2  # q1 has 2 candidates
    assert train_stats["max_candidates_per_query"] == 2


def test_build_annotation_manifest_schema():
    queries = _queries()
    pool = prepare_pool(_pool(), queries, "r1")
    a = build_annotator_frame(pool, seed=1, annotator="A")
    b = build_annotator_frame(pool, seed=1, annotator="B", splits=["val", "test"])
    split_stats = build_split_stats(pool)

    manifest = build_annotation_manifest("r1", queries, a, b, split_stats)

    assert manifest["annotation_round"] == "r1"
    assert manifest["query_splits"] == {"train": 1, "val": 1, "test": 1}
    assert manifest["annotator_A"]["rows"] == len(a)
    assert manifest["annotator_B"]["rows"] == len(b)
    assert manifest["relevance"]["binary_relevance_threshold"] == 2
