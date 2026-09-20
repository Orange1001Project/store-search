from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from store_search_ai.evaluation.evaluator import (
    bootstrap_ci,
    build_evaluation_report,
    calculate_metrics,
    compare_runs,
    load_qrels,
    load_run,
    paired_permutation_pvalue,
    save_evaluation_outputs,
    validate_run,
)


def _write_trec_qrels(path: Path, rows: list[tuple[str, str, int]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for query_id, doc_id, relevance in rows:
            f.write(f"{query_id} 0 {doc_id} {relevance}\n")


def _write_run_csv(path: Path, rows: list[tuple[str, str, int, float]]) -> None:
    pd.DataFrame(rows, columns=["query_id", "doc_id", "rank", "score"]).to_csv(
        path, index=False, encoding="utf-8-sig"
    )


def test_bootstrap_ci_is_deterministic_for_a_fixed_seed():
    values = [0.1, 0.5, 0.9, 0.3, 0.7]
    first = bootstrap_ci(values, samples=500, seed=42)
    second = bootstrap_ci(values, samples=500, seed=42)
    assert first == second
    assert first[0] <= first[1]


def test_bootstrap_ci_empty_input_returns_none_pair():
    assert bootstrap_ci([], samples=100, seed=1) == [None, None]


def test_paired_permutation_pvalue_zero_diff_is_not_significant():
    diffs = np.zeros(20)
    p = paired_permutation_pvalue(diffs, samples=1000, seed=1)
    assert p == pytest.approx(1.0)


def test_paired_permutation_pvalue_empty_returns_none():
    assert paired_permutation_pvalue([], samples=100, seed=1) is None


def test_load_qrels_trec_and_csv_agree(tmp_path):
    rows = [("q1", "d1", 3), ("q1", "d2", 0), ("q2", "d1", 1)]

    trec_path = tmp_path / "qrels.trec"
    _write_trec_qrels(trec_path, rows)
    trec_qrels = {(q.query_id, q.doc_id): q.relevance for q in load_qrels(trec_path)}

    csv_path = tmp_path / "qrels.csv"
    pd.DataFrame(rows, columns=["query_id", "doc_id", "relevance"]).to_csv(
        csv_path, index=False, encoding="utf-8-sig"
    )
    csv_qrels = {(q.query_id, q.doc_id): q.relevance for q in load_qrels(csv_path)}

    assert trec_qrels == csv_qrels == {("q1", "d1"): 3, ("q1", "d2"): 0, ("q2", "d1"): 1}


def test_load_qrels_rejects_duplicate_pairs(tmp_path):
    path = tmp_path / "qrels.csv"
    pd.DataFrame(
        [("q1", "d1", 3), ("q1", "d1", 1)], columns=["query_id", "doc_id", "relevance"]
    ).to_csv(path, index=False, encoding="utf-8-sig")
    with pytest.raises(ValueError, match="duplicate"):
        load_qrels(path)


def test_load_run_rejects_non_positive_rank(tmp_path):
    path = tmp_path / "run.csv"
    _write_run_csv(path, [("q1", "d1", 0, 1.0)])
    with pytest.raises(ValueError, match="rank"):
        load_run(path)


def test_calculate_metrics_perfect_run_gives_ndcg_one(tmp_path):
    qrels_path = tmp_path / "qrels.trec"
    _write_trec_qrels(qrels_path, [("q1", "d1", 3), ("q1", "d2", 0)])
    run_path = tmp_path / "run.csv"
    _write_run_csv(run_path, [("q1", "d1", 1, 1.0), ("q1", "d2", 2, 0.5)])

    aggregate, per_query = calculate_metrics(load_qrels(qrels_path), load_run(run_path))

    assert aggregate["nDCG@10"] == pytest.approx(1.0)
    assert list(per_query["query_id"]) == ["q1"]


def test_validate_run_flags_unknown_query_ids(tmp_path):
    run_path = tmp_path / "run.csv"
    _write_run_csv(run_path, [("q_unexpected", "d1", 1, 1.0)])
    with pytest.raises(ValueError, match="unknown query_ids"):
        validate_run(run_path, expected_query_ids={"q1"})


def test_validate_run_reports_missing_queries_without_raising(tmp_path):
    run_path = tmp_path / "run.csv"
    _write_run_csv(run_path, [("q1", "d1", 1, 1.0)])
    result = validate_run(run_path, expected_query_ids={"q1", "q2"})
    assert result["missing_queries"] == 1
    assert result["unknown_queries"] == 0


def test_compare_runs_identical_runs_have_zero_delta(tmp_path):
    qrels_path = tmp_path / "qrels.trec"
    _write_trec_qrels(qrels_path, [("q1", "d1", 3), ("q1", "d2", 0), ("q2", "d1", 2)])
    run_path = tmp_path / "run.csv"
    _write_run_csv(run_path, [("q1", "d1", 1, 1.0), ("q1", "d2", 2, 0.5), ("q2", "d1", 1, 1.0)])

    qrels = load_qrels(qrels_path)
    run = load_run(run_path)
    _, per_query = calculate_metrics(qrels, run)

    comparison = compare_runs(per_query, per_query, bootstrap_samples=200, seed=1)
    assert comparison["nDCG@10"]["delta_mean"] == pytest.approx(0.0)
    assert comparison["nDCG@10"]["wins"] == 0
    assert comparison["nDCG@10"]["losses"] == 0


def test_build_evaluation_report_and_save_round_trip(tmp_path):
    qrels_path = tmp_path / "qrels.trec"
    _write_trec_qrels(qrels_path, [("q1", "d1", 3), ("q1", "d2", 0)])
    run_path = tmp_path / "run.csv"
    _write_run_csv(run_path, [("q1", "d1", 1, 1.0), ("q1", "d2", 2, 0.5)])

    report, per_query = build_evaluation_report(
        qrels_path=qrels_path,
        run_path=run_path,
        tag="unit_test",
        bootstrap_samples=200,
        seed=1,
    )

    assert report["tag"] == "unit_test"
    assert report["aggregate"]["nDCG@10"] == pytest.approx(1.0)
    assert "comparison" not in report

    output_dir = tmp_path / "out"
    per_query_path, evaluation_path = save_evaluation_outputs(report, per_query, output_dir, "unit_test")
    assert per_query_path.exists()
    assert evaluation_path.exists()


def test_build_evaluation_report_with_compare_run_adds_comparison(tmp_path):
    qrels_path = tmp_path / "qrels.trec"
    _write_trec_qrels(qrels_path, [("q1", "d1", 3), ("q1", "d2", 0)])
    run_path = tmp_path / "run_new.csv"
    _write_run_csv(run_path, [("q1", "d1", 1, 1.0), ("q1", "d2", 2, 0.5)])
    baseline_path = tmp_path / "run_base.csv"
    _write_run_csv(baseline_path, [("q1", "d2", 1, 1.0), ("q1", "d1", 2, 0.5)])

    report, _ = build_evaluation_report(
        qrels_path=qrels_path,
        run_path=run_path,
        tag="new",
        bootstrap_samples=200,
        seed=1,
        compare_run_path=baseline_path,
        compare_tag="base",
    )

    assert report["comparison"]["baseline_tag"] == "base"
    assert "nDCG@10" in report["comparison"]["metrics"]
