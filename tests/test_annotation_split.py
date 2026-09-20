import pandas as pd
import pytest

from store_search_ai.data.annotation_split import (
    split_by_column,
    validate_splits_present,
)


def test_validate_splits_present_passes_when_all_present():
    df = pd.DataFrame({"split": ["train", "val", "test"]})
    validate_splits_present(df, ["train", "val", "test"], source_label="test.csv")  # no raise


def test_validate_splits_present_raises_when_missing():
    df = pd.DataFrame({"split": ["train", "val"]})
    with pytest.raises(ValueError, match=r"\['test'\]"):
        validate_splits_present(df, ["train", "val", "test"], source_label="test.csv")


def test_split_by_column_partitions_rows_preserving_other_columns():
    df = pd.DataFrame(
        {"split": ["train", "val", "train"], "relevance": [3, 2, 1], "uncertain": ["", "Y", ""]}
    )
    parts = split_by_column(df, "split", ["train", "val"])
    assert list(parts["train"]["relevance"]) == [3, 1]
    assert list(parts["val"]["relevance"]) == [2]
    assert list(parts["val"]["uncertain"]) == ["Y"]


def test_split_by_column_returns_empty_frame_for_value_not_in_data():
    df = pd.DataFrame({"split": ["train"]})
    parts = split_by_column(df, "split", ["train", "test"])
    assert len(parts["test"]) == 0
