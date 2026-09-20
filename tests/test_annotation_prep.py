import pandas as pd
import pytest

from store_search_ai.data.annotation_prep import (
    build_adjudication_frame,
    build_agreement_report,
    build_full_annotation_summary,
    build_needed_adjudication,
    build_partial_agreement_qrels,
    load_completed,
    pairwise_report,
    split_train_qrels,
    truthy,
    validate_expected_splits,
)

COMMON_COLUMNS = [
    "judgment_id", "query_id", "query", "intent_definition", "split", "query_family",
    "query_type", "doc_id", "store_name", "item_text", "market_name", "market_type",
    "source_region", "relevance", "uncertain", "annotator_note",
]


def _row(judgment_id, query_id, doc_id, split, relevance, uncertain=""):
    return {
        "judgment_id": judgment_id, "query_id": query_id, "query": "치킨",
        "intent_definition": "치킨", "split": split, "query_family": "치킨",
        "query_type": "exact", "doc_id": doc_id, "store_name": "s", "item_text": "치킨",
        "market_name": "", "market_type": "", "source_region": "서울",
        "relevance": relevance, "uncertain": uncertain, "annotator_note": "",
    }


def test_truthy_recognizes_known_true_values():
    series = pd.Series(["Y", "yes", "TRUE", "1", "N", "", None])
    assert list(truthy(series)) == [True, True, True, True, False, False, False]


def test_load_completed_rejects_missing_columns(tmp_path):
    path = tmp_path / "a.csv"
    pd.DataFrame({"judgment_id": ["j1"]}).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_completed(path)


def test_load_completed_rejects_duplicate_judgment_id(tmp_path):
    path = tmp_path / "a.csv"
    pd.DataFrame([_row("j1", "q1", "d1", "train", 3), _row("j1", "q1", "d2", "train", 2)]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )
    with pytest.raises(ValueError, match="duplicate judgment_id"):
        load_completed(path)


def test_load_completed_rejects_invalid_relevance(tmp_path):
    path = tmp_path / "a.csv"
    pd.DataFrame([_row("j1", "q1", "d1", "train", 9)]).to_csv(path, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="invalid relevance"):
        load_completed(path)


def test_load_completed_sets_uncertain_flag(tmp_path):
    path = tmp_path / "a.csv"
    pd.DataFrame([_row("j1", "q1", "d1", "train", 3, uncertain="Y")]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )
    df = load_completed(path)
    assert df.iloc[0]["uncertain_flag"] == True


def test_validate_expected_splits_raises_on_mismatch():
    data = {
        "A_train": pd.DataFrame({"split": ["val"]}),
        "A_val": pd.DataFrame({"split": ["val"]}),
        "A_test": pd.DataFrame({"split": ["test"]}),
        "B_val": pd.DataFrame({"split": ["val"]}),
        "B_test": pd.DataFrame({"split": ["test"]}),
    }
    with pytest.raises(ValueError, match="expected split=train"):
        validate_expected_splits(data)


def test_split_train_qrels_excludes_uncertain_and_missing():
    train = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3.0, "query_family": "f", "uncertain_flag": False},
            {"query_id": "q1", "doc_id": "d2", "relevance": float("nan"), "query_family": "f", "uncertain_flag": False},
            {"query_id": "q1", "doc_id": "d3", "relevance": 2.0, "query_family": "f", "uncertain_flag": True},
        ]
    )
    qrels, usable, excluded = split_train_qrels(train)
    assert list(qrels["doc_id"]) == ["d1"]
    assert qrels.iloc[0]["relevance"] == 3
    assert len(usable) == 1
    assert len(excluded) == 2


def _ab(judgment_id, query_id, doc_id, rel_a, rel_b, uncertain_a="", uncertain_b=""):
    a = _row(judgment_id, query_id, doc_id, "val", rel_a, uncertain_a)
    b = _row(judgment_id, query_id, doc_id, "val", rel_b, uncertain_b)
    return a, b


def test_pairwise_report_exact_agreement_auto_finalizes():
    a_rows, b_rows = zip(_ab("j1", "q1", "d1", 3, 3))
    a = pd.DataFrame(a_rows)
    b = pd.DataFrame(b_rows)
    merged, report = pairwise_report(a, b, "val")

    assert merged.iloc[0]["exact_agree"] == True
    assert merged.iloc[0]["needs_adjudication"] == False
    assert merged.iloc[0]["final_relevance"] == 3
    assert merged.iloc[0]["adjudication_priority"] == "RESOLVED_AGREEMENT"
    assert report["exact_agreement"] == 1.0


def test_pairwise_report_binary_threshold_mismatch_is_p1():
    a_rows, b_rows = zip(_ab("j1", "q1", "d1", 3, 0))
    a = pd.DataFrame(a_rows)
    b = pd.DataFrame(b_rows)
    merged, _ = pairwise_report(a, b, "val")
    assert merged.iloc[0]["adjudication_priority"] == "P1_BINARY_THRESHOLD"
    assert merged.iloc[0]["needs_adjudication"] == True


def test_pairwise_report_same_side_of_threshold_is_p2():
    a_rows, b_rows = zip(_ab("j1", "q1", "d1", 3, 2))
    a = pd.DataFrame(a_rows)
    b = pd.DataFrame(b_rows)
    merged, _ = pairwise_report(a, b, "val")
    assert merged.iloc[0]["adjudication_priority"] == "P2_GRADED_ONLY"


def test_pairwise_report_uncertain_is_p0():
    a_rows, b_rows = zip(_ab("j1", "q1", "d1", 3, 3, uncertain_a="Y"))
    a = pd.DataFrame(a_rows)
    b = pd.DataFrame(b_rows)
    merged, report = pairwise_report(a, b, "val")
    assert merged.iloc[0]["adjudication_priority"] == "P0_UNCERTAIN_OR_MISSING"
    assert report["exact_agreement"] is None  # no valid pairs


def test_pairwise_report_rejects_mismatched_judgment_ids():
    a = pd.DataFrame([_row("j1", "q1", "d1", "val", 3)])
    b = pd.DataFrame([_row("j2", "q1", "d1", "val", 3)])
    with pytest.raises(ValueError, match="not identical"):
        pairwise_report(a, b, "val")


def _merged_pair(judgment_id="j1", needs_adjudication=False, final_relevance=3):
    a_rows, b_rows = zip(_ab(judgment_id, "q1", "d1", final_relevance, final_relevance))
    a = pd.DataFrame(a_rows)
    b = pd.DataFrame(b_rows)
    merged, _ = pairwise_report(a, b, "val")
    merged["needs_adjudication"] = needs_adjudication
    return merged


def test_build_adjudication_frame_adds_empty_editable_columns():
    val_merged = _merged_pair()
    test_merged = _merged_pair(judgment_id="j2")
    frame = build_adjudication_frame(val_merged, test_merged)
    assert len(frame) == 2
    assert {"assistant_suggested_relevance", "human_adjudication_note", "exclude_from_gold"} <= set(frame.columns)


def test_build_needed_adjudication_filters_and_sorts():
    val_merged = _merged_pair(judgment_id="j1", needs_adjudication=True)
    test_merged = _merged_pair(judgment_id="j2", needs_adjudication=False)
    frame = build_adjudication_frame(val_merged, test_merged)
    needed = build_needed_adjudication(frame)
    assert list(needed["judgment_id"]) == ["j1"]


def test_build_partial_agreement_qrels_only_keeps_resolved_rows():
    merged = _merged_pair(judgment_id="j1", needs_adjudication=False, final_relevance=2)
    merged2 = _merged_pair(judgment_id="j2", needs_adjudication=True, final_relevance=3)
    combined = pd.concat([merged, merged2], ignore_index=True)
    agreed = build_partial_agreement_qrels(combined)
    assert list(agreed["doc_id"]) == ["d1"]
    assert "relevance" in agreed.columns and "final_relevance" not in agreed.columns


def test_build_full_annotation_summary_schema():
    train = pd.DataFrame({"query_id": ["q1", "q1"], "relevance": [3.0, float("nan")]})
    train_usable = pd.DataFrame({"query_id": ["q1"], "relevance": [3.0]})
    val_report = {"split": "val"}
    test_report = {"split": "test"}
    needed = pd.DataFrame({"adjudication_priority": ["P1_BINARY_THRESHOLD"]})

    summary = build_full_annotation_summary(train, train_usable, val_report, test_report, needed)
    assert summary["benchmark_status"] == "PROVISIONAL"
    assert summary["train"]["rows"] == 2
    assert summary["train"]["usable_for_training"] == 1
    assert summary["train"]["excluded_uncertain"] == 1
    assert summary["total_adjudication_rows"] == 1


def test_build_agreement_report_computes_coverage_and_kappa():
    val_merged = _merged_pair(judgment_id="j1", needs_adjudication=False, final_relevance=3)
    test_merged = _merged_pair(judgment_id="j2", needs_adjudication=False, final_relevance=2)
    report = build_agreement_report(val_merged, test_merged, binary_threshold=2)
    assert report["human_double_annotation_required_rows"] == 2
    assert report["double_annotation_coverage"] == pytest.approx(1.0)
    assert report["exact_agreement"] == pytest.approx(1.0)
    assert report["binary_relevance_threshold"] == 2
