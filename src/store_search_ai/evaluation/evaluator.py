"""StoreSearch-KO v1 공식 IR evaluator.

scripts/13_evaluate_run.py의 CLI 배관(인자 파싱, 콘솔 출력)을 제외한 채점 로직 전체.
**이 모듈이 유일한 채점 구현이다** — nDCG/Recall/Precision 등을 여기서 직접
재구현하지 않고 전부 `ir_measures`에 위임한다. 14_run_model_eval.py의 docstring이
설명하듯, 원본 프로젝트에는 이 계산을 독립적으로 재구현한 `evaluation/metrics.py`가
따로 있어서 두 구현이 어긋날 위험이 있었다 — 그 문제를 반복하지 않기 위해 이 모듈은
일부러 그 이름을 쓰지 않았고, 계산 로직 자체도 절대 복제하지 않는다.
scripts/14_run_model_eval.py, scripts/15_score_model_runs.py는 여전히
scripts/13_evaluate_run.py를 서브프로세스로 호출한다(코드를 import하지 않음) — 그래야
"모든 모델의 run은 동일 evaluator를 거친다"는 원칙이 CLI 계약으로도 강제된다.
"""

from __future__ import annotations

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
    """Supports .trec and .csv (query_id, doc_id, relevance)."""

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
            raise ValueError(f"Qrels CSV missing columns: {sorted(missing)}")

        df = df[["query_id", "doc_id", "relevance"]].copy()
        df["query_id"] = df["query_id"].astype(str)
        df["doc_id"] = df["doc_id"].astype(str)
        df["relevance"] = pd.to_numeric(df["relevance"], errors="coerce")

        if df["relevance"].isna().any():
            raise ValueError("Qrels contains non-numeric relevance values.")

        if df.duplicated(["query_id", "doc_id"]).any():
            raise ValueError("Qrels contains duplicate query_id/doc_id pairs.")

        return [
            ir_measures.Qrel(str(r.query_id), str(r.doc_id), int(r.relevance))
            for r in df.itertuples(index=False)
        ]

    raise ValueError(f"Unsupported qrels format: {path.suffix}")


def load_run(path: Path):
    """Supports .trec and .csv (query_id, doc_id, rank, score[, system])."""

    if not path.exists():
        raise FileNotFoundError(f"Run file not found: {path}")

    if path.suffix.lower() == ".trec":
        # Same reasoning as load_qrels(): materialize the generator, and open
        # as UTF-8 ourselves to avoid the OS-locale-encoding trap on Korean query_id.
        with path.open("r", encoding="utf-8") as f:
            return list(ir_measures.read_trec_run(f))

    if path.suffix.lower() == ".csv":
        df = pd.read_csv(path, encoding="utf-8-sig")

        required = {"query_id", "doc_id", "rank", "score"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"Run CSV missing columns: {sorted(missing)}")

        df = df.copy()
        df["query_id"] = df["query_id"].astype(str)
        df["doc_id"] = df["doc_id"].astype(str)
        df["rank"] = pd.to_numeric(df["rank"], errors="coerce")
        df["score"] = pd.to_numeric(df["score"], errors="coerce")

        if df["rank"].isna().any():
            raise ValueError("Run contains invalid rank values.")
        if df["score"].isna().any():
            raise ValueError("Run contains invalid score values.")
        if (df["rank"] <= 0).any():
            raise ValueError("Run rank must be >= 1.")
        if df.duplicated(["query_id", "doc_id"]).any():
            raise ValueError("Run contains duplicate query_id/doc_id pairs.")

        return [
            ir_measures.ScoredDoc(str(r.query_id), str(r.doc_id), float(r.score))
            for r in df.itertuples(index=False)
        ]

    raise ValueError(f"Unsupported run format: {path.suffix}")


# ============================================================
# Metric calculation
# ============================================================

def calculate_metrics(qrels, run):
    measures = [ir_measures.parse_measure(spec) for spec in METRIC_SPECS.values()]

    aggregate = ir_measures.calc_aggregate(measures, qrels, run)

    per_query_rows = []
    for result in ir_measures.iter_calc(measures, qrels, run):
        internal_name = str(result.measure)

        public_name = None
        for name, spec in METRIC_SPECS.items():
            if str(ir_measures.parse_measure(spec)) == internal_name:
                public_name = name
                break
        if public_name is None:
            public_name = internal_name

        per_query_rows.append(
            {"query_id": str(result.query_id), "metric": public_name, "value": float(result.value)}
        )

    per_query_long = pd.DataFrame(per_query_rows)
    if per_query_long.empty:
        raise ValueError("No per-query metric results were produced.")

    per_query = per_query_long.pivot(index="query_id", columns="metric", values="value").reset_index()

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

def bootstrap_ci(values, samples: int, seed: int):
    """Query-level non-parametric bootstrap. Returns percentile 95% CI."""

    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [None, None]

    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(x), size=(samples, len(x)))
    means = x[indices].mean(axis=1)

    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def paired_permutation_pvalue(diffs, samples: int, seed: int):
    """Two-sided paired randomization/permutation test. H0: mean difference = 0."""

    d = np.asarray(diffs, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return None

    observed = abs(float(d.mean()))

    rng = np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(samples, len(d)))
    permuted = np.abs((signs * d).mean(axis=1))

    p = (np.sum(permuted >= observed) + 1) / (samples + 1)
    return float(p)


def compare_runs(new_per_query: pd.DataFrame, base_per_query: pd.DataFrame, bootstrap_samples: int, seed: int):
    """Compare two systems query-by-query. All official metrics are compared."""

    merged = new_per_query.merge(base_per_query, on="query_id", suffixes=("_new", "_base"), how="inner")
    if len(merged) == 0:
        raise ValueError("No overlapping query_ids between runs.")

    comparison = {}
    for metric in METRIC_SPECS:
        new_col = f"{metric}_new"
        base_col = f"{metric}_base"
        if new_col not in merged.columns or base_col not in merged.columns:
            continue

        diffs = merged[new_col].to_numpy() - merged[base_col].to_numpy()
        diffs = diffs[np.isfinite(diffs)]
        if len(diffs) == 0:
            continue

        comparison[metric] = {
            "delta_mean": float(diffs.mean()),
            "delta_ci95": bootstrap_ci(diffs, bootstrap_samples, seed),
            "paired_permutation_pvalue": paired_permutation_pvalue(diffs, bootstrap_samples, seed + 1),
            "wins": int((diffs > 0).sum()),
            "ties": int((diffs == 0).sum()),
            "losses": int((diffs < 0).sum()),
        }

    return comparison


# ============================================================
# Run validation
# ============================================================

def validate_run(run_path: Path, expected_query_ids: set[str]):
    """Basic integrity checks for submitted model runs."""

    df = pd.read_csv(run_path, encoding="utf-8-sig")

    required = {"query_id", "doc_id", "rank", "score"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Run CSV missing columns: {sorted(missing)}")

    actual_queries = set(df["query_id"].astype(str))
    unknown_queries = actual_queries - expected_query_ids
    if unknown_queries:
        raise ValueError(f"Run contains unknown query_ids: {sorted(unknown_queries)[:10]}")

    missing_queries = expected_query_ids - actual_queries
    # Missing queries are reported as warning, rather than automatically fatal.
    duplicate_pairs = df.duplicated(["query_id", "doc_id"]).sum()
    invalid_rank = (pd.to_numeric(df["rank"], errors="coerce") <= 0).sum()

    return {
        "rows": len(df),
        "queries": int(df["query_id"].nunique()),
        "expected_queries": len(expected_query_ids),
        "missing_queries": len(missing_queries),
        "unknown_queries": len(unknown_queries),
        "duplicate_query_doc_pairs": int(duplicate_pairs),
        "invalid_rank_rows": int(invalid_rank),
    }


# ============================================================
# Orchestration (used by scripts/13_evaluate_run.py)
# ============================================================

def build_evaluation_report(
    qrels_path: Path,
    run_path: Path,
    tag: str,
    bootstrap_samples: int,
    seed: int,
    compare_run_path: Path | None = None,
    compare_tag: str = "baseline",
) -> tuple[dict, pd.DataFrame]:
    """qrels/run을 로드해 지표를 계산하고, (report dict, per_query DataFrame)을 반환한다.

    파일 저장은 하지 않는 순수 계산 — CLI가 이 결과를 그대로 저장/출력한다.
    """

    qrels = load_qrels(qrels_path)
    run = load_run(run_path)

    aggregate, per_query = calculate_metrics(qrels, run)

    expected_query_ids = {str(q.query_id) for q in qrels}

    run_validation = None
    if run_path.suffix.lower() == ".csv":
        run_validation = validate_run(run_path, expected_query_ids)

    confidence_intervals = {}
    for metric in METRIC_SPECS:
        if metric not in per_query.columns:
            continue
        values = per_query[metric].to_numpy()
        confidence_intervals[metric] = {
            "mean": float(np.nanmean(values)),
            "ci95": bootstrap_ci(values, bootstrap_samples, seed),
        }

    report = {
        "benchmark": "StoreSearch-KO v1",
        "tag": tag,
        "qrels": str(qrels_path),
        "run": str(run_path),
        "primary_metric": PRIMARY_METRIC,
        "binary_relevance_threshold": BINARY_THRESHOLD,
        "metrics": list(METRIC_SPECS.keys()),
        "query_count": len(expected_query_ids),
        "run_query_count": int(per_query["query_id"].nunique()),
        "aggregate": aggregate,
        "query_bootstrap_ci95": confidence_intervals,
        "run_validation": run_validation,
    }

    if compare_run_path is not None:
        baseline_qrels = load_qrels(qrels_path)
        baseline_run = load_run(compare_run_path)
        baseline_aggregate, baseline_per_query = calculate_metrics(baseline_qrels, baseline_run)

        comparison = compare_runs(per_query, baseline_per_query, bootstrap_samples, seed)

        report["comparison"] = {
            "baseline_tag": compare_tag,
            "baseline_run": str(compare_run_path),
            "baseline_aggregate": baseline_aggregate,
            "metrics": comparison,
            "note": (
                "For multiple pairwise model comparisons, apply Holm correction to the resulting p-values."
            ),
        }

    return report, per_query


def save_evaluation_outputs(
    report: dict, per_query: pd.DataFrame, output_dir: Path, tag: str
) -> tuple[Path, Path]:
    """per_query.csv + evaluation.json을 저장하고 (per_query_path, evaluation_path)를 반환한다."""

    output_dir.mkdir(parents=True, exist_ok=True)

    per_query_path = output_dir / f"{tag}_per_query.csv"
    evaluation_path = output_dir / f"{tag}_evaluation.json"

    per_query.to_csv(per_query_path, index=False, encoding="utf-8-sig")
    evaluation_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return per_query_path, evaluation_path
