import json
from datetime import UTC, datetime

import pytest

from store_search_ai.training.finetune import (
    CHECKPOINT_SUFFIX,
    KEEP_MARKER,
    PARTIAL_SUFFIX,
    config_mismatches,
    expand_training_rows,
    latest_checkpoint,
    make_run_tag,
    prune_finetune_runs,
    run_tag_prefix,
    validate_resume_tag,
)


def _record(query, positives, negatives):
    return {"query_id": query, "query": query, "positives": positives, "negatives": negatives}


def test_make_run_tag_includes_owner_and_utc_minute():
    now = datetime(2026, 9, 28, 3, 7, tzinfo=UTC)
    assert make_run_tag("bge_m3", "jisu", now) == "bge_m3_ft_jisu_20260928_0307"
    assert make_run_tag("bge_m3", "jisu", now).startswith(run_tag_prefix("bge_m3", "jisu"))


@pytest.mark.parametrize("owner", ["", "Jisu", "j", "ji su", "1jisu"])
def test_make_run_tag_rejects_invalid_owner(owner):
    with pytest.raises(ValueError, match="OWNER"):
        make_run_tag("bge_m3", owner)


def test_expand_training_rows_one_row_per_positive_with_fixed_negative_columns():
    records = [_record("국밥", ["p1", "p2"], ["n1", "n2", "n3"])]
    rows, stats = expand_training_rows(records, num_hard_negatives=2, max_positives_per_query=None)
    assert rows == [
        {"anchor": "국밥", "positive": "p1", "negative_1": "n1", "negative_2": "n2"},
        {"anchor": "국밥", "positive": "p2", "negative_1": "n1", "negative_2": "n2"},
    ]
    assert stats == {"n_queries_in_file": 1, "n_queries_used": 1, "n_skipped_few_negatives": 0, "n_rows": 2}


def test_expand_training_rows_skips_queries_with_too_few_negatives():
    records = [_record("a", ["p"], ["n1"]), _record("b", ["p"], ["n1", "n2"])]
    rows, stats = expand_training_rows(records, num_hard_negatives=2, max_positives_per_query=None)
    assert [row["anchor"] for row in rows] == ["b"]
    assert stats["n_skipped_few_negatives"] == 1
    # 모든 행의 컬럼이 같아야 Trainer가 읽을 수 있다
    assert {tuple(row) for row in rows} == {("anchor", "positive", "negative_1", "negative_2")}


def test_expand_training_rows_caps_positives_per_query_keeping_first():
    records = [_record("a", ["p1", "p2", "p3"], [])]
    rows, _ = expand_training_rows(records, num_hard_negatives=0, max_positives_per_query=2)
    assert [row["positive"] for row in rows] == ["p1", "p2"]


def test_expand_training_rows_reads_legacy_single_positive_schema():
    records = [{"query_id": "a", "query": "a", "positive": "p", "negatives": ["n"]}]
    rows, _ = expand_training_rows(records, num_hard_negatives=1, max_positives_per_query=None)
    assert rows == [{"anchor": "a", "positive": "p", "negative_1": "n"}]


def _make_run(root, name, created_at, keep=False, manifest=True):
    run_dir = root / name
    run_dir.mkdir()
    if manifest:
        (run_dir / "model_manifest.json").write_text(json.dumps({"created_at": created_at}), encoding="utf-8")
    if keep:
        (run_dir / KEEP_MARKER).write_text("", encoding="utf-8")
    return run_dir


def test_prune_keeps_latest_runs_and_protects_keep_others_and_incomplete(tmp_path):
    prefix = run_tag_prefix("bge_m3", "jisu")
    old = _make_run(tmp_path, f"{prefix}20260901_0000", "2026-09-01T00:00:00+00:00")
    kept = _make_run(tmp_path, f"{prefix}20260902_0000", "2026-09-02T00:00:00+00:00", keep=True)
    mid = _make_run(tmp_path, f"{prefix}20260903_0000", "2026-09-03T00:00:00+00:00")
    new = _make_run(tmp_path, f"{prefix}20260904_0000", "2026-09-04T00:00:00+00:00")
    other_owner = _make_run(tmp_path, "bge_m3_ft_minho_20260801_0000", "2026-08-01T00:00:00+00:00")
    other_model = _make_run(tmp_path, "arctic_ko_ft_jisu_20260801_0000", "2026-08-01T00:00:00+00:00")
    partial = _make_run(tmp_path, f"{prefix}20260801_0000{PARTIAL_SUFFIX}", "2026-08-01T00:00:00+00:00")
    no_manifest = _make_run(tmp_path, f"{prefix}20260801_0100", "", manifest=False)

    assert prune_finetune_runs(tmp_path, prefix, keep_last=2, dry_run=True) == [old]
    assert old.exists()

    assert prune_finetune_runs(tmp_path, prefix, keep_last=2) == [old]
    assert not old.exists()
    for survivor in (kept, mid, new, other_owner, other_model, partial, no_manifest):
        assert survivor.exists()


def test_prune_rejects_keep_last_zero(tmp_path):
    with pytest.raises(ValueError):
        prune_finetune_runs(tmp_path, "x_", keep_last=0)


def test_prune_ignores_checkpoint_dirs(tmp_path):
    prefix = run_tag_prefix("bge_m3", "jisu")
    ckpt = tmp_path / f"{prefix}20260801_0000{CHECKPOINT_SUFFIX}"
    (ckpt / "checkpoint-10").mkdir(parents=True)
    _make_run(tmp_path, f"{prefix}20260902_0000", "2026-09-02T00:00:00+00:00")
    assert prune_finetune_runs(tmp_path, prefix, keep_last=1) == []
    assert ckpt.exists()


def test_validate_resume_tag_accepts_own_run_and_rejects_others():
    assert validate_resume_tag(" bge_m3_ft_jisu_20260928_0307 ", "bge_m3", "jisu") == "bge_m3_ft_jisu_20260928_0307"
    with pytest.raises(ValueError, match="RESUME_TAG"):
        validate_resume_tag("bge_m3_ft_minho_20260928_0307", "bge_m3", "jisu")
    with pytest.raises(ValueError, match="RESUME_TAG"):
        validate_resume_tag("arctic_ko_ft_jisu_20260928_0307", "bge_m3", "jisu")


def test_latest_checkpoint_picks_highest_step_numerically(tmp_path):
    assert latest_checkpoint(tmp_path / "missing") is None
    assert latest_checkpoint(tmp_path) is None
    for name in ("checkpoint-9", "checkpoint-120", "checkpoint-33", "runs"):
        (tmp_path / name).mkdir()
    (tmp_path / "checkpoint-999.tmp").mkdir()
    assert latest_checkpoint(tmp_path) == tmp_path / "checkpoint-120"


def test_config_mismatches_ignores_resume_only_keys():
    saved = {"learning_rate": 2e-5, "batch_size": 32, "note": "a", "resume_tag": None, "train_pairs_sha256": "x"}
    same = {**saved, "note": "b", "resume_tag": "bge_m3_ft_jisu_20260928_0307"}
    assert config_mismatches(saved, same) == []
    changed = {**same, "batch_size": 16, "train_pairs_sha256": "y"}
    assert config_mismatches(saved, changed) == ["batch_size", "train_pairs_sha256"]


def test_package_tree_sha256_changes_on_edit_and_ignores_cache(tmp_path):
    from store_search_ai.training.finetune import (
        iter_package_files,
        package_tree_sha256,
    )

    pkg = tmp_path / "store_search_ai"
    (pkg / "training").mkdir(parents=True)
    (pkg / "training" / "st_finetune.py").write_text("lr = 1\n", encoding="utf-8")
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    before = package_tree_sha256(pkg)

    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"cache")
    assert package_tree_sha256(pkg) == before
    assert [p.name for p in iter_package_files(pkg)] == ["__init__.py", "st_finetune.py"]

    (pkg / "training" / "st_finetune.py").write_text("lr = 2\n", encoding="utf-8")
    assert package_tree_sha256(pkg) != before
