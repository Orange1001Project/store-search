import pandas as pd
import pytest

from store_search_ai.data.adjudication_patch import (
    apply_adjudication_patch,
    build_patch_report,
    validate_patch,
)


def _full():
    return pd.DataFrame(
        [
            {"judgment_id": "j1", "query_id": "q1", "store_name": "s1", "final_relevance": pd.NA},
            {"judgment_id": "j2", "query_id": "q1", "store_name": "s2", "final_relevance": pd.NA},
            {"judgment_id": "j3", "query_id": "q2", "store_name": "s3", "final_relevance": 3},
        ]
    )


def test_validate_patch_rejects_duplicate_judgment_id():
    patch = pd.DataFrame([{"judgment_id": "j1"}, {"judgment_id": "j1"}])
    with pytest.raises(ValueError, match="duplicate"):
        validate_patch(_full(), patch)


def test_validate_patch_rejects_unknown_judgment_id():
    patch = pd.DataFrame([{"judgment_id": "j_unknown"}])
    with pytest.raises(ValueError, match="unknown judgment_ids"):
        validate_patch(_full(), patch)


def test_validate_patch_rejects_invalid_final_relevance():
    patch = pd.DataFrame([{"judgment_id": "j1", "final_relevance": 9}])
    with pytest.raises(ValueError, match="Allowed values: 0, 1, 2, 3"):
        validate_patch(_full(), patch)


def test_validate_patch_allows_missing_final_relevance_when_excluded():
    patch = pd.DataFrame([{"judgment_id": "j1", "final_relevance": None, "exclude_from_gold": "Y"}])
    validate_patch(_full(), patch)  # no raise


def test_apply_adjudication_patch_fills_final_relevance():
    patch = pd.DataFrame(
        [
            {"judgment_id": "j1", "final_relevance": 2, "exclude_from_gold": "", "human_adjudication_note": "ok"},
            {"judgment_id": "j2", "final_relevance": None, "exclude_from_gold": "Y", "human_adjudication_note": "excluded"},
        ]
    )
    result = apply_adjudication_patch(_full(), patch)

    row_j1 = result.set_index("judgment_id").loc["j1"]
    assert row_j1["final_relevance"] == 2
    row_j2 = result.set_index("judgment_id").loc["j2"]
    assert pd.isna(row_j2["final_relevance"])
    assert row_j2["exclude_from_gold"] == "Y"
    # untouched row keeps its original value
    assert result.set_index("judgment_id").loc["j3", "final_relevance"] == 3


def test_apply_adjudication_patch_adds_missing_columns_with_correct_dtype():
    full = _full().drop(columns=["final_relevance"])
    full["final_relevance"] = pd.NA
    patch = pd.DataFrame([{"judgment_id": "j1", "final_relevance": 1}])
    result = apply_adjudication_patch(full, patch)
    assert "human_adjudication_note" in result.columns
    assert "exclude_from_gold" in result.columns


def test_build_patch_report_flags_unresolved_non_excluded_rows():
    patch = pd.DataFrame(
        [
            {"judgment_id": "j1", "final_relevance": None, "exclude_from_gold": ""},
        ]
    )
    result = apply_adjudication_patch(_full(), patch)
    report = build_patch_report(result, patch)

    assert report["patch_rows"] == 1
    assert report["patch_final_relevance_filled"] == 0
    assert report["unresolved_non_excluded"] == 2  # j1 (unresolved) + j2 (never patched, still NA)
    assert "j1" in set(report["unresolved_rows"]["judgment_id"])


def test_build_patch_report_zero_unresolved_when_all_resolved_or_excluded():
    patch = pd.DataFrame(
        [
            {"judgment_id": "j1", "final_relevance": 2, "exclude_from_gold": ""},
            {"judgment_id": "j2", "final_relevance": None, "exclude_from_gold": "Y"},
        ]
    )
    result = apply_adjudication_patch(_full(), patch)
    report = build_patch_report(result, patch)
    assert report["unresolved_non_excluded"] == 0
