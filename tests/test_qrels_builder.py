
import pandas as pd
import pytest

from store_search_ai.data.qrels_builder import (
    assemble_qrels,
    build_manifest,
    build_split_qrels,
    freeze_benchmark,
    load_adjudication,
    load_train_qrels,
    manifest_json,
    save_qrels_outputs,
    split_summary,
    truthy,
    validate_qrels,
)


def test_truthy_recognizes_known_true_values_case_insensitively():
    for value in ["Y", "y", "yes", "TRUE", "1"]:
        assert truthy(value) is True


def test_truthy_false_for_none_nan_and_other_strings():
    assert truthy(None) is False
    assert truthy(float("nan")) is False
    assert truthy("N") is False
    assert truthy("") is False


def test_validate_qrels_rejects_duplicates():
    qrels = pd.DataFrame({"query_id": ["q1", "q1"], "doc_id": ["d1", "d1"], "relevance": [1, 2]})
    with pytest.raises(ValueError, match="duplicate"):
        validate_qrels(qrels, "val")


def test_validate_qrels_rejects_out_of_range_grades():
    qrels = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "relevance": [5]})
    with pytest.raises(ValueError, match="invalid relevance"):
        validate_qrels(qrels, "val")


def test_validate_qrels_rejects_empty():
    qrels = pd.DataFrame({"query_id": [], "doc_id": [], "relevance": []})
    with pytest.raises(ValueError, match="empty"):
        validate_qrels(qrels, "val")


def _adjudication_frame(rows):
    return pd.DataFrame(
        rows, columns=["query_id", "doc_id", "split", "query_family", "final_relevance", "exclude_from_gold"]
    )


def test_build_split_qrels_excludes_rows_marked_exclude_from_gold():
    adj = _adjudication_frame(
        [
            ("q1", "d1", "val", "fam", 3, "N"),
            ("q1", "d2", "val", "fam", None, "Y"),  # excluded, so unresolved final_relevance is fine
        ]
    )
    qrels = build_split_qrels(adj, "val")
    assert len(qrels) == 1
    assert qrels.iloc[0]["doc_id"] == "d1"
    assert qrels.iloc[0]["relevance"] == 3


def test_build_split_qrels_raises_on_unresolved_non_excluded_row():
    adj = _adjudication_frame([("q1", "d1", "val", "fam", None, "N")])
    with pytest.raises(ValueError, match="unresolved"):
        build_split_qrels(adj, "val")


def test_build_split_qrels_filters_by_split():
    adj = _adjudication_frame(
        [("q1", "d1", "val", "fam", 3, "N"), ("q2", "d1", "test", "fam", 2, "N")]
    )
    qrels = build_split_qrels(adj, "val")
    assert set(qrels["query_id"]) == {"q1"}


def test_load_adjudication_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_adjudication(tmp_path / "missing.csv")


def test_load_adjudication_missing_columns_raises(tmp_path):
    path = tmp_path / "adj.csv"
    pd.DataFrame({"query_id": ["q1"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_adjudication(path)


def test_load_train_qrels_requires_query_family(tmp_path):
    path = tmp_path / "train.csv"
    pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "relevance": [3]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="query_family"):
        load_train_qrels(path)


def test_assemble_qrels_adds_split_column_and_detects_cross_split_duplicates():
    def frame(query_id, doc_id, relevance):
        return pd.DataFrame(
            {"query_id": [query_id], "doc_id": [doc_id], "relevance": [relevance], "query_family": ["fam"]}
        )

    train = frame("q1", "d1", 3)
    val = frame("q2", "d1", 2)
    test = frame("q3", "d1", 1)

    result = assemble_qrels(train, val, test, active_query_ids={"q1", "q2", "q3"})
    assert set(result) == {"train", "val", "test", "all"}
    assert list(result["train"]["split"]) == ["train"]
    assert len(result["all"]) == 3


def test_assemble_qrels_rejects_duplicate_query_doc_pair_across_splits():
    def frame(split_marker):
        return pd.DataFrame(
            {"query_id": ["q1"], "doc_id": ["d1"], "relevance": [3], "query_family": ["fam"]}
        )

    with pytest.raises(ValueError, match="Duplicate query_id/doc_id"):
        assemble_qrels(frame("train"), frame("val"), pd.DataFrame(
            {"query_id": [], "doc_id": [], "relevance": [], "query_family": []}
        ), active_query_ids={"q1"})


def test_assemble_qrels_rejects_unknown_query_id():
    frame = pd.DataFrame({"query_id": ["q_unexpected"], "doc_id": ["d1"], "relevance": [3], "query_family": ["fam"]})
    empty = pd.DataFrame({"query_id": [], "doc_id": [], "relevance": [], "query_family": []})
    with pytest.raises(ValueError, match="not present in active queries"):
        assemble_qrels(frame, empty, empty, active_query_ids={"q1"})


def test_split_summary_computes_grade_distribution_and_binary_relevant():
    frame = pd.DataFrame({"query_id": ["q1", "q1", "q2"], "relevance": [3, 0, 2]})
    summary = split_summary(frame)
    assert summary["queries"] == 2
    assert summary["judgments"] == 3
    assert summary["grade_distribution"] == {"0": 1, "2": 1, "3": 1}
    assert summary["binary_relevant_ge_2"] == 2


def test_save_qrels_outputs_writes_csv_and_trec(tmp_path):
    frame = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "relevance": [3], "query_family": ["fam"], "split": ["train"]})
    frames = {"train": frame, "val": frame, "test": frame, "all": frame}
    csv_paths, trec_paths = save_qrels_outputs(tmp_path, frames)

    assert csv_paths["train"] == tmp_path / "qrels_train.csv"
    assert csv_paths["all"] == tmp_path / "qrels.csv"
    assert trec_paths["all"] == tmp_path / "qrels.trec"
    assert csv_paths["train"].exists()
    assert trec_paths["train"].read_text(encoding="utf-8").strip() == "q1 0 d1 3"


def test_build_manifest_schema(tmp_path):
    frame = pd.DataFrame({"query_id": ["q1"], "doc_id": ["d1"], "relevance": [3], "query_family": ["fam"], "split": ["train"]})
    frames = {"train": frame, "val": frame, "test": frame, "all": frame}
    csv_paths, trec_paths = save_qrels_outputs(tmp_path, frames)
    queries_path = tmp_path / "queries.csv"
    queries_path.write_text("query_id\nq1\n", encoding="utf-8")

    manifest = build_manifest(
        config={"benchmark_version": "v1", "dataset_version": "d1", "corpus_version": "c1"},
        active_query_count=1,
        qrels_frames=frames,
        queries_path=queries_path,
        csv_paths=csv_paths,
        trec_paths=trec_paths,
        adjudication_path=tmp_path / "adj.csv",
        train_path=tmp_path / "train.csv",
        sha256_file=lambda p: "deadbeef",
    )

    assert manifest["benchmark_status"] == "PROVISIONAL"
    assert manifest["query_count"] == 1
    assert manifest["files"]["qrels_train.csv"] == "deadbeef"
    assert manifest_json(manifest).startswith("{")


def test_freeze_benchmark_copies_files_and_refuses_to_overwrite(tmp_path):
    source = tmp_path / "source.csv"
    source.write_text("data", encoding="utf-8")
    frozen_dir = tmp_path / "frozen"

    freeze_benchmark(frozen_dir, [source])
    assert (frozen_dir / "source.csv").read_text(encoding="utf-8") == "data"

    with pytest.raises(FileExistsError):
        freeze_benchmark(frozen_dir, [source])
