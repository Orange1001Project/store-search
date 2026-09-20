from pathlib import Path

import pytest

from store_search_ai.models.model_eval import (
    build_encoder,
    build_evaluate_run_cmd,
    build_manifest_entry,
)


def test_build_encoder_dummy_returns_random_encoder():
    encoder = build_encoder(dummy=True, model_config_path=None)
    assert type(encoder).__name__ == "RandomEncoder"


def test_build_encoder_requires_model_config_when_not_dummy():
    with pytest.raises(SystemExit, match="--model-config"):
        build_encoder(dummy=False, model_config_path=None)


def test_build_evaluate_run_cmd_shapes_argv():
    cmd = build_evaluate_run_cmd(
        "python", Path("scripts/13_evaluate_run.py"), Path("qrels_val.trec"), Path("run.csv"), "tag_val"
    )
    assert cmd == [
        "python", str(Path("scripts/13_evaluate_run.py")),
        "--qrels", str(Path("qrels_val.trec")),
        "--run", str(Path("run.csv")),
        "--tag", "tag_val",
    ]


def test_build_manifest_entry_uses_given_timestamp_when_provided():
    entry = build_manifest_entry(
        split="val", template="t1_minimal", eval_tag="model_val",
        aggregate_metrics={"nDCG@10": 0.5}, evaluated_at="2026-01-01T00:00:00+00:00",
    )
    assert entry == {
        "evaluated_at": "2026-01-01T00:00:00+00:00",
        "split": "val",
        "template": "t1_minimal",
        "tag": "model_val",
        "metrics": {"nDCG@10": 0.5},
    }


def test_build_manifest_entry_defaults_to_current_utc_time_when_omitted():
    entry = build_manifest_entry(split="val", template="t1_minimal", eval_tag="tag", aggregate_metrics={})
    assert entry["evaluated_at"].endswith("+00:00")
