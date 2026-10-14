"""qrels가 바뀐 뒤(보충 판정 라운드 등) 이미 있는 공식 평가를 **같은 run 파일로 다시 채점**한다 — 모델을 다시 돌리지 않는다.

    artifacts/evaluation/<benchmark_version>/*_evaluation.json  (import_colab_results.py가 가져온 공식 평가)
      → run: results/model_eval/<tag>/run_<template>_<split>.csv  (같은 이름으로 가져온 run 파일)
      → 새 qrels로 build_evaluation_report(공식 evaluator) → evaluation.json·per_query.csv 덮어쓰기
      → results/experiments.csv의 같은 eval_tag 줄 지표 갱신

모델·인코딩 정보(model_id, eval_dtype, library_versions, evaluated_at 등)는 그대로 두고, 지표와 `rescored`(언제, 어떤
qrels로, 이전 지표)만 바꾼다. test 평가는 `--include-test`를 줄 때만 다시 채점한다(test 점수를 새로 보는 일이므로).
쿼리를 비활성화한 뒤(queries.csv status=inactive)라면 run 파일에서 그 쿼리 행을 지우고 채점한다(공식 evaluator는 qrels에
없는 쿼리가 run에 있으면 멈추므로). `--dry-run`은 run 파일을 건드리지 않는다.

사용법:
    python scripts/rescore_evaluations.py --dry-run     # 무엇을 다시 채점할지만 출력
    python scripts/rescore_evaluations.py
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

import pandas as pd

from store_search_ai.evaluation.evaluator import (
    build_evaluation_report,
    save_evaluation_outputs,
)
from store_search_ai.pipeline.common import load_config, sha256_file

KEPT_FIELDS = ("official", "corpus_docs", "model_id", "eval_dtype", "evaluated_at", "library_versions", "evaluated_with")
REGISTRY_METRICS = ("nDCG@10", "Judged@10", "Recall@100", "MRR@100", "Bpref")


def local_run(repo_root: Path, run: str) -> Path:
    """report의 run 경로(Colab /content/drive/... 또는 로컬)를 저장소 results/model_eval/<tag>/<file>로 바꾼다."""

    path = PureWindowsPath(run)   # / 와 \ 를 둘 다 구분자로 읽는다
    return repo_root / "results" / "model_eval" / path.parent.name / path.name


def drop_inactive_queries(run_path: Path, inactive: set[str]) -> int:
    """run 파일에서 비활성 쿼리(queries.csv status=inactive) 행을 지우고 지운 쿼리 수를 돌려준다.

    공식 evaluator는 qrels에 없는 query_id가 run에 있으면 멈춘다(엄격하게 두는 것이 의도). 쿼리를 비활성화하기 전에 만든
    run에는 그 쿼리 결과가 들어 있으므로, 비활성 쿼리만 빼고 다시 저장한다 — 그 밖의 모르는 query_id는 그대로 둬서 에러가 난다.
    """

    # pandas로 읽고 쓰면 score의 마지막 자리가 바뀔 수 있어(evaluator는 score로 정렬) 줄 단위로 그대로 거른다
    header, *lines = run_path.read_text(encoding="utf-8-sig").splitlines(keepends=True)
    kept = [line for line in lines if line.split(",", 1)[0] not in inactive]
    if len(kept) != len(lines):
        run_path.write_text(header + "".join(kept), encoding="utf-8-sig", newline="")
    return len({line.split(",", 1)[0] for line in lines} & inactive)


def rescore_report(
    old: dict, repo_root: Path, benchmark_dir: Path, bootstrap: int, seed: int, inactive: set[str] = frozenset()
) -> tuple[dict, pd.DataFrame]:
    run_path = local_run(repo_root, old["run"])
    split = run_path.stem.rsplit("_", 1)[-1]
    comparison = old.get("comparison") or {}
    baseline = local_run(repo_root, comparison["baseline_run"]) if comparison.get("baseline_run") else None
    dropped = {str(p.parent.name): n for p in filter(None, (run_path, baseline)) if (n := drop_inactive_queries(p, inactive))}
    qrels_path = benchmark_dir / f"qrels_{split}.trec"
    report, per_query = build_evaluation_report(
        qrels_path=qrels_path, run_path=run_path, tag=old["tag"], bootstrap_samples=bootstrap, seed=seed,
        compare_run_path=baseline, compare_tag=comparison.get("baseline_tag", "baseline"),
    )
    report["run"] = old["run"]   # import_colab_results가 run 경로의 폴더·파일 이름으로 run을 찾으므로 원래 값 유지
    if baseline is not None:
        report["comparison"]["baseline_run"] = comparison["baseline_run"]
    report.update({k: old[k] for k in KEPT_FIELDS if k in old})
    report["rescored"] = {
        "rescored_at": datetime.now(UTC).isoformat(),
        "qrels_sha256": sha256_file(qrels_path),
        "previous_aggregate": old.get("aggregate"),
        "previous_rescored": old.get("rescored"),
    }
    if dropped:
        report["rescored"]["inactive_queries_dropped_from_runs"] = dropped
    return report, per_query


def update_registry(path: Path, reports: list[dict]) -> int:
    """experiments.csv에서 같은 eval_tag 줄의 지표만 새 값으로 바꾼다(다른 열·다른 줄은 그대로)."""

    if not path.exists():
        return 0
    table = pd.read_csv(path, encoding="utf-8-sig")
    updated = 0
    for report in reports:
        mask = table["eval_tag"] == report["tag"]
        if not mask.any():
            continue
        for metric in REGISTRY_METRICS:
            table.loc[mask, metric] = report["aggregate"].get(metric)
        ndcg = (report.get("comparison") or {}).get("metrics", {}).get("nDCG@10", {})
        table.loc[mask, "delta_nDCG@10"] = ndcg.get("delta_mean")
        table.loc[mask, "p_nDCG@10"] = ndcg.get("paired_permutation_pvalue")
        updated += int(mask.sum())
    table.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--include-test", action="store_true", help="test 평가도 다시 채점(최종 평가 뒤에만)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo_root = Path.cwd()
    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    eval_dir = repo_root / "artifacts" / "evaluation" / config["benchmark_version"]
    settings = config.get("evaluation", {})
    bootstrap, seed = int(settings.get("bootstrap_samples", 10000)), int(settings.get("random_seed", 20260831))
    queries = pd.read_csv(benchmark_dir / "queries.csv", encoding="utf-8-sig")
    inactive = set(queries.loc[queries["status"].astype(str).str.lower() != "active", "query_id"].astype(str))

    reports = []
    for path in sorted(eval_dir.glob("*_evaluation.json")):
        old = json.loads(path.read_text(encoding="utf-8"))
        run_path = local_run(repo_root, old["run"])
        if run_path.stem.endswith("_test") and not args.include_test:
            print(f"[건너뜀] test 평가: {path.name} (--include-test로만)")
            continue
        if not run_path.exists():
            raise SystemExit(f"{path.name}: run 파일이 없습니다 {run_path} — import_colab_results.py로 먼저 가져오세요.")
        if args.dry_run:
            print(f"[예정] {path.name}  ← {run_path.relative_to(repo_root)}")
            continue
        report, per_query = rescore_report(old, repo_root, benchmark_dir, bootstrap, seed, inactive)
        save_evaluation_outputs(report, per_query, eval_dir, old["tag"])
        before, after = old["aggregate"], report["aggregate"]
        print(f"[재채점] {old['tag']}: nDCG@10 {before['nDCG@10']:.4f} → {after['nDCG@10']:.4f}, "
              f"Judged@10 {before['Judged@10']:.4f} → {after['Judged@10']:.4f}")
        reports.append(report)
    if reports:
        updated = update_registry(repo_root / "results" / "experiments.csv", reports)
        print(f"[기록] results/experiments.csv {updated}줄 지표 갱신")


if __name__ == "__main__":
    main()
