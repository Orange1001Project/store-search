from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

# ir_measures.util.parse_measure() (used for specs like "P(rel=2)@10") walks
# a parsed AST and checks `isinstance(node, ast.Num)` — removed in Python 3.12
# (superseded by ast.Constant back in 3.8). Rather than pin the whole project
# to Python <3.12 just for this, patch the one broken helper before anything
# imports/uses it. Safe to remove once ir_measures ships a real fix upstream.
if not hasattr(ast, "Num"):
    import ir_measures.util as _ir_util

    def _ast_to_value_compat(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Dict):
            return dict(
                zip(
                    map(_ast_to_value_compat, node.keys),
                    map(_ast_to_value_compat, node.values),
                )
            )
        raise ValueError("values must be str, float, int, bool, etc.")

    _ir_util._ast_to_value = _ast_to_value_compat

import ir_measures


# ============================================================
# StoreSearch-KO v1 Official Evaluation Metrics
# ============================================================

METRIC_SPECS = {
    "nDCG@10": "nDCG@10",
    "Precision@10": "P(rel=2)@10",
    "MRR@100": "RR(rel=2)@100",
    "Recall@50": "R(rel=2)@50",
    "Recall@100": "R(rel=2)@100",
    "Bpref": "Bpref(rel=2)",
    "Judged@10": "Judged@10",
    "Judged@100": "Judged@100",
}

PRIMARY_METRIC = "nDCG@10"
BINARY_THRESHOLD = 2


# ============================================================
# File loading
# ============================================================

def load_qrels(path: Path):
    """
    Supports:
      - .trec
      - .csv

    CSV must contain:
      query_id, doc_id, relevance
    """

    if not path.exists():
        raise FileNotFoundError(f"Qrels file not found: {path}")

    if path.suffix.lower() == ".trec":
        # NOTE: ir_measures.read_trec_qrels() returns a one-shot generator.
        # calculate_metrics() below consumes qrels twice (aggregate + per-query),
        # so it must be materialized into a list here.
        # NOTE: passing a path string makes ir_measures open() the file with the
        # OS locale encoding (cp949 on Korean Windows), which breaks on the
        # Korean characters in our query_id (e.g. "q_치킨_01"). Open it ourselves
        # as UTF-8 and hand over the file object instead (read_trec_qrels reads
        # file-like objects as-is without re-opening them).
        with path.open("r", encoding="utf-8") as f:
            return list(ir_measures.read_trec_qrels(f))

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")

        required = {"query_id", "doc_id", "relevance"}
        missing = required - set(df.columns)

        if missing:
            raise ValueError(
                f"Qrels CSV missing columns: {sorted(missing)}"
            )

        df = df[
            ["query_id", "doc_id", "relevance"]
        ].copy()

        df["query_id"] = df["query_id"].astype(str)
        df["doc_id"] = df["doc_id"].astype(str)

        df["relevance"] = pd.to_numeric(
            df["relevance"],
            errors="coerce",
        )

        if df["relevance"].isna().any():
            raise ValueError(
                "Qrels contains non-numeric relevance values."
            )

        if df.duplicated(
            ["query_id", "doc_id"]
        ).any():
            raise ValueError(
                "Qrels contains duplicate query_id/doc_id pairs."
            )

        rows = [
            ir_measures.Qrel(
                str(r.query_id),
                str(r.doc_id),
                int(r.relevance),
            )
            for r in df.itertuples(index=False)
        ]

        return rows

    raise ValueError(
        f"Unsupported qrels format: {path.suffix}"
    )


def load_run(path: Path):
    """
    Supports:
      - .trec
      - .csv

    CSV must contain:
      query_id, doc_id, rank, score

    Optional:
      system
    """

    if not path.exists():
        raise FileNotFoundError(f"Run file not found: {path}")

    if path.suffix.lower() == ".trec":
        # Same reasoning as load_qrels(): materialize the generator, and open
        # as UTF-8 ourselves to avoid the OS-locale-encoding trap on Korean query_id.
        with path.open("r", encoding="utf-8") as f:
            return list(ir_measures.read_trec_run(f))

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")

        required = {
            "query_id",
            "doc_id",
            "rank",
            "score",
        }

        missing = required - set(df.columns)

        if missing:
            raise ValueError(
                f"Run CSV missing columns: {sorted(missing)}"
            )

        df = df.copy()

        df["query_id"] = df["query_id"].astype(str)
        df["doc_id"] = df["doc_id"].astype(str)

        df["rank"] = pd.to_numeric(
            df["rank"],
            errors="coerce",
        )

        df["score"] = pd.to_numeric(
            df["score"],
            errors="coerce",
        )

        if df["rank"].isna().any():
            raise ValueError(
                "Run contains invalid rank values."
            )

        if df["score"].isna().any():
            raise ValueError(
                "Run contains invalid score values."
            )

        if (df["rank"] <= 0).any():
            raise ValueError(
                "Run rank must be >= 1."
            )

        if df.duplicated(
            ["query_id", "doc_id"]
        ).any():
            raise ValueError(
                "Run contains duplicate query_id/doc_id pairs."
            )

        rows = [
            ir_measures.ScoredDoc(
                str(r.query_id),
                str(r.doc_id),
                float(r.score),
            )
            for r in df.itertuples(index=False)
        ]

        return rows

    raise ValueError(
        f"Unsupported run format: {path.suffix}"
    )


# ============================================================
# Metric calculation
# ============================================================

def calculate_metrics(qrels, run):
    measures = [
        ir_measures.parse_measure(spec)
        for spec in METRIC_SPECS.values()
    ]

    aggregate = ir_measures.calc_aggregate(
        measures,
        qrels,
        run,
    )

    per_query_rows = []

    for result in ir_measures.iter_calc(
        measures,
        qrels,
        run,
    ):
        internal_name = str(result.measure)

        public_name = None

        for name, spec in METRIC_SPECS.items():
            if str(
                ir_measures.parse_measure(spec)
            ) == internal_name:
                public_name = name
                break

        if public_name is None:
            public_name = internal_name

        per_query_rows.append(
            {
                "query_id": str(result.query_id),
                "metric": public_name,
                "value": float(result.value),
            }
        )

    per_query_long = pd.DataFrame(
        per_query_rows
    )

    if per_query_long.empty:
        raise ValueError(
            "No per-query metric results were produced."
        )

    per_query = (
        per_query_long
        .pivot(
            index="query_id",
            columns="metric",
            values="value",
        )
        .reset_index()
    )

    aggregate_public = {}

    for name, spec in METRIC_SPECS.items():
        parsed = ir_measures.parse_measure(spec)

        for key, value in aggregate.items():
            if str(key) == str(parsed):
                aggregate_public[name] = float(value)
                break

    return aggregate_public, per_query


# ============================================================
# Statistical analysis
# ============================================================

def bootstrap_ci(
    values,
    samples: int,
    seed: int,
):
    """
    Query-level non-parametric bootstrap.
    Returns percentile 95% CI.
    """

    x = np.asarray(
        values,
        dtype=float,
    )

    x = x[np.isfinite(x)]

    if len(x) == 0:
        return [None, None]

    rng = np.random.default_rng(seed)

    indices = rng.integers(
        0,
        len(x),
        size=(samples, len(x)),
    )

    means = x[indices].mean(axis=1)

    return [
        float(np.quantile(means, 0.025)),
        float(np.quantile(means, 0.975)),
    ]


def paired_permutation_pvalue(
    diffs,
    samples: int,
    seed: int,
):
    """
    Two-sided paired randomization/permutation test.

    Null hypothesis:
      mean difference = 0
    """

    d = np.asarray(
        diffs,
        dtype=float,
    )

    d = d[np.isfinite(d)]

    if len(d) == 0:
        return None

    observed = abs(float(d.mean()))

    rng = np.random.default_rng(seed)

    signs = rng.choice(
        np.array([-1.0, 1.0]),
        size=(samples, len(d)),
    )

    permuted = np.abs(
        (signs * d).mean(axis=1)
    )

    p = (
        np.sum(permuted >= observed) + 1
    ) / (samples + 1)

    return float(p)


def compare_runs(
    new_per_query: pd.DataFrame,
    base_per_query: pd.DataFrame,
    bootstrap_samples: int,
    seed: int,
):
    """
    Compare two systems query-by-query.

    All official metrics are compared.
    """

    merged = new_per_query.merge(
        base_per_query,
        on="query_id",
        suffixes=("_new", "_base"),
        how="inner",
    )

    if len(merged) == 0:
        raise ValueError(
            "No overlapping query_ids between runs."
        )

    comparison = {}

    for metric in METRIC_SPECS.keys():

        new_col = f"{metric}_new"
        base_col = f"{metric}_base"

        if (
            new_col not in merged.columns
            or base_col not in merged.columns
        ):
            continue

        diffs = (
            merged[new_col].to_numpy()
            - merged[base_col].to_numpy()
        )

        finite = np.isfinite(diffs)

        diffs = diffs[finite]

        if len(diffs) == 0:
            continue

        comparison[metric] = {
            "delta_mean": float(diffs.mean()),
            "delta_ci95": bootstrap_ci(
                diffs,
                bootstrap_samples,
                seed,
            ),
            "paired_permutation_pvalue": (
                paired_permutation_pvalue(
                    diffs,
                    bootstrap_samples,
                    seed + 1,
                )
            ),
            "wins": int(
                (diffs > 0).sum()
            ),
            "ties": int(
                (diffs == 0).sum()
            ),
            "losses": int(
                (diffs < 0).sum()
            ),
        }

    return comparison


# ============================================================
# Run validation
# ============================================================

def validate_run(
    run_path: Path,
    expected_query_ids: set[str],
):
    """
    Basic integrity checks for submitted model runs.
    """

    df = pd.read_csv(
        run_path,
        encoding="utf-8-sig",
    )

    required = {
        "query_id",
        "doc_id",
        "rank",
        "score",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(
            f"Run CSV missing columns: {sorted(missing)}"
        )

    actual_queries = set(
        df["query_id"]
        .astype(str)
    )

    unknown_queries = (
        actual_queries
        - expected_query_ids
    )

    if unknown_queries:
        raise ValueError(
            "Run contains unknown query_ids: "
            f"{sorted(unknown_queries)[:10]}"
        )

    missing_queries = (
        expected_query_ids
        - actual_queries
    )

    # Missing queries are reported as warning,
    # rather than automatically fatal.
    duplicate_pairs = df.duplicated(
        ["query_id", "doc_id"]
    ).sum()

    invalid_rank = (
        pd.to_numeric(
            df["rank"],
            errors="coerce",
        )
        <= 0
    ).sum()

    return {
        "rows": int(len(df)),
        "queries": int(
            df["query_id"].nunique()
        ),
        "expected_queries": int(
            len(expected_query_ids)
        ),
        "missing_queries": int(
            len(missing_queries)
        ),
        "unknown_queries": int(
            len(unknown_queries)
        ),
        "duplicate_query_doc_pairs": int(
            duplicate_pairs
        ),
        "invalid_rank_rows": int(
            invalid_rank
        ),
    }


# ============================================================
# Main
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "StoreSearch-KO v1 official IR evaluator"
        )
    )

    parser.add_argument(
        "--qrels",
        default=(
            "benchmark/storesearch_ko_v1/"
            "qrels_val.trec"
        ),
        help=(
            "Qrels CSV or TREC file"
        ),
    )

    parser.add_argument(
        "--run",
        required=True,
        help=(
            "Model run CSV or TREC file"
        ),
    )

    parser.add_argument(
        "--tag",
        required=True,
        help=(
            "Experiment/system tag"
        ),
    )

    parser.add_argument(
        "--compare-run",
        default=None,
        help=(
            "Optional baseline run for paired comparison"
        ),
    )

    parser.add_argument(
        "--compare-tag",
        default="baseline",
    )

    parser.add_argument(
        "--output-dir",
        default=(
            "artifacts/evaluation/"
            "storesearch_ko_v1"
        ),
    )

    parser.add_argument(
        "--bootstrap",
        type=int,
        default=10000,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=20260831,
    )

    args = parser.parse_args()

    qrels_path = Path(args.qrels)
    run_path = Path(args.run)
    output_dir = Path(args.output_dir)

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Load
    # --------------------------------------------------------

    qrels = load_qrels(qrels_path)
    run = load_run(run_path)

    # --------------------------------------------------------
    # Calculate
    # --------------------------------------------------------

    aggregate, per_query = calculate_metrics(
        qrels,
        run,
    )

    # --------------------------------------------------------
    # Expected queries
    # --------------------------------------------------------

    expected_query_ids = {
        str(q.query_id)
        for q in qrels
    }

    run_validation = None

    if run_path.suffix.lower() == ".csv":
        run_validation = validate_run(
            run_path,
            expected_query_ids,
        )

    # --------------------------------------------------------
    # Bootstrap confidence intervals
    # --------------------------------------------------------

    confidence_intervals = {}

    for metric in METRIC_SPECS.keys():

        if metric not in per_query.columns:
            continue

        values = per_query[
            metric
        ].to_numpy()

        confidence_intervals[metric] = {
            "mean": float(
                np.nanmean(values)
            ),
            "ci95": bootstrap_ci(
                values,
                args.bootstrap,
                args.seed,
            ),
        }

    # --------------------------------------------------------
    # Report
    # --------------------------------------------------------

    report = {
        "benchmark": "StoreSearch-KO v1",
        "tag": args.tag,
        "qrels": str(qrels_path),
        "run": str(run_path),

        "primary_metric": PRIMARY_METRIC,

        "binary_relevance_threshold": (
            BINARY_THRESHOLD
        ),

        "metrics": list(
            METRIC_SPECS.keys()
        ),

        "query_count": int(
            len(expected_query_ids)
        ),

        "run_query_count": int(
            per_query["query_id"].nunique()
        ),

        "aggregate": aggregate,

        "query_bootstrap_ci95": (
            confidence_intervals
        ),

        "run_validation": run_validation,
    }

    # --------------------------------------------------------
    # Optional paired comparison
    # --------------------------------------------------------

    if args.compare_run:

        baseline_path = Path(
            args.compare_run
        )

        baseline_qrels = load_qrels(
            qrels_path
        )

        baseline_run = load_run(
            baseline_path
        )

        baseline_aggregate, baseline_per_query = (
            calculate_metrics(
                baseline_qrels,
                baseline_run,
            )
        )

        comparison = compare_runs(
            per_query,
            baseline_per_query,
            args.bootstrap,
            args.seed,
        )

        report["comparison"] = {
            "baseline_tag": args.compare_tag,
            "baseline_run": str(
                baseline_path
            ),
            "baseline_aggregate": (
                baseline_aggregate
            ),
            "metrics": comparison,
            "note": (
                "For multiple pairwise model "
                "comparisons, apply Holm correction "
                "to the resulting p-values."
            ),
        }

    # --------------------------------------------------------
    # Save
    # --------------------------------------------------------

    per_query_path = (
        output_dir
        / f"{args.tag}_per_query.csv"
    )

    evaluation_path = (
        output_dir
        / f"{args.tag}_evaluation.json"
    )

    per_query.to_csv(
        per_query_path,
        index=False,
        encoding="utf-8-sig",
    )

    evaluation_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Console
    # --------------------------------------------------------

    print()
    print(
        "========== StoreSearch-KO IR EVALUATION =========="
    )
    print()

    print(
        f"tag             = {args.tag}"
    )

    print(
        f"qrels           = {qrels_path}"
    )

    print(
        f"run             = {run_path}"
    )

    print(
        f"queries         = {len(expected_query_ids)}"
    )

    print()

    print(
        "---------- OFFICIAL METRICS ----------"
    )

    for metric in METRIC_SPECS.keys():

        if metric not in aggregate:
            continue

        value = aggregate[metric]

        ci = confidence_intervals.get(
            metric
        )

        if ci:
            low, high = ci["ci95"]

            print(
                f"{metric:<15} = "
                f"{value:.4f} "
                f"[95% CI {low:.4f}, {high:.4f}]"
            )

        else:
            print(
                f"{metric:<15} = "
                f"{value:.4f}"
            )

    print()

    if args.compare_run:

        print(
            "---------- PAIRED COMPARISON ----------"
        )

        for metric, result in (
            report["comparison"]["metrics"]
            .items()
        ):

            print(
                f"{metric:<15} "
                f"delta={result['delta_mean']:.4f} "
                f"p={result['paired_permutation_pvalue']:.4f} "
                f"wins={result['wins']} "
                f"ties={result['ties']} "
                f"losses={result['losses']}"
            )

        print()

    print(
        f"per-query output = {per_query_path}"
    )

    print(
        f"evaluation JSON  = {evaluation_path}"
    )

    print()

    print(
        "=================================================="
    )


if __name__ == "__main__":
    main()