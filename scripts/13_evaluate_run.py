"""StoreSearch-KO v1 공식 IR evaluator — **단 하나**의 채점 경로.

모든 모델·모든 실험의 run.csv가 반드시 이 스크립트를 거쳐야 점수가 나온다.
`scripts/14_run_model_eval.py`, `scripts/15_score_model_runs.py`는 이 스크립트를
서브프로세스로 호출할 뿐 채점 로직을 복제하지 않는다 — 그래서 이 스크립트의 CLI
인자(`--qrels`, `--run`, `--tag`, ...)와 출력 파일 이름/경로는 하위 호환을 유지해야 한다.

채점 로직 자체는 src/store_search_ai/evaluation/evaluator.py에 있다. 이 스크립트는
인자 파싱, 파일 저장, 콘솔 출력만 담당한다.

사용 예:
    python scripts/13_evaluate_run.py --run results/model_eval/bge_m3/run_t1_minimal_val.csv --tag bge_m3_val
    python scripts/13_evaluate_run.py --run new_run.csv --tag new --compare-run old_run.csv --compare-tag old
"""

from __future__ import annotations

import argparse
from pathlib import Path

from store_search_ai.evaluation.evaluator import (
    METRIC_SPECS,
    build_evaluation_report,
    save_evaluation_outputs,
)
from store_search_ai.pipeline.common import load_config


def print_console_summary(report: dict, per_query_path: Path, evaluation_path: Path) -> None:
    aggregate = report["aggregate"]
    confidence_intervals = report["query_bootstrap_ci95"]

    print()
    print("========== StoreSearch-KO IR EVALUATION ==========")
    print()
    print(f"tag             = {report['tag']}")
    print(f"qrels           = {report['qrels']}")
    print(f"run             = {report['run']}")
    print(f"queries         = {report['query_count']}")
    print()
    print("---------- OFFICIAL METRICS ----------")
    for metric in METRIC_SPECS:
        if metric not in aggregate:
            continue
        value = aggregate[metric]
        ci = confidence_intervals.get(metric)
        if ci:
            low, high = ci["ci95"]
            print(f"{metric:<15} = {value:.4f} [95% CI {low:.4f}, {high:.4f}]")
        else:
            print(f"{metric:<15} = {value:.4f}")
    print()

    if "comparison" in report:
        print("---------- PAIRED COMPARISON ----------")
        for metric, result in report["comparison"]["metrics"].items():
            print(
                f"{metric:<15} delta={result['delta_mean']:.4f} "
                f"p={result['paired_permutation_pvalue']:.4f} "
                f"wins={result['wins']} ties={result['ties']} losses={result['losses']}"
            )
        print()

    print(f"per-query output = {per_query_path}")
    print(f"evaluation JSON  = {evaluation_path}")
    print()
    print("==================================================")


def main():
    parser = argparse.ArgumentParser(description="StoreSearch-KO v1 official IR evaluator")
    parser.add_argument("--qrels", default="benchmark/storesearch_ko_v1/qrels_val.trec", help="Qrels CSV or TREC file")
    parser.add_argument("--run", required=True, help="Model run CSV or TREC file")
    parser.add_argument("--tag", required=True, help="Experiment/system tag")
    parser.add_argument("--compare-run", default=None, help="Optional baseline run for paired comparison")
    parser.add_argument("--compare-tag", default="baseline")
    parser.add_argument("--output-dir", default="artifacts/evaluation/storesearch_ko_v1")
    parser.add_argument(
        "--config",
        default="configs/benchmark/storesearch_ko_v1.yaml",
        help="--bootstrap/--seed 기본값을 여기 evaluation.* 에서 읽는다 (명시적으로 주면 그 값이 우선)",
    )
    parser.add_argument("--bootstrap", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    # --bootstrap/--seed을 명시하지 않으면 configs/benchmark/storesearch_ko_v1.yaml의
    # evaluation.bootstrap_samples/evaluation.random_seed를 단일 소스로 쓴다. 예전에는 이
    # 스크립트가 두 값을 각자 하드코딩된 CLI 기본값(20260831/10000)으로만 갖고 있어서,
    # yaml의 evaluation.random_seed/bootstrap_samples는 아무도 읽지 않는 죽은 설정값이었다
    # (query_set.random_seed가 겪었던 것과 같은 종류의 어긋남 위험 — PR #1 리뷰에서 발견).
    eval_config = load_config(args.config).get("evaluation", {})
    bootstrap_samples = args.bootstrap if args.bootstrap is not None else int(eval_config.get("bootstrap_samples", 10000))
    seed = args.seed if args.seed is not None else int(eval_config.get("random_seed", 20260831))

    report, per_query = build_evaluation_report(
        qrels_path=Path(args.qrels),
        run_path=Path(args.run),
        tag=args.tag,
        bootstrap_samples=bootstrap_samples,
        seed=seed,
        compare_run_path=Path(args.compare_run) if args.compare_run else None,
        compare_tag=args.compare_tag,
    )

    per_query_path, evaluation_path = save_evaluation_outputs(
        report, per_query, Path(args.output_dir), args.tag
    )

    print_console_summary(report, per_query_path, evaluation_path)


if __name__ == "__main__":
    main()
