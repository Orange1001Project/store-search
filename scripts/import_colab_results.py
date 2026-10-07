"""Colab(Drive)에서 끝낸 실험 결과를 로컬 저장소 구조로 가져온다 — 실험이 다 끝난 뒤 마지막에 한 번.

Colab 노트북이 Drive `store-search-ai/runs/` 밑에 쌓은 것을 저장소의 정해진 자리로 옮긴다:

    runs/model_eval/<tag>/run_*.csv                → results/model_eval/<tag>/
    runs/evaluation/*_evaluation.json, *_per_query  → artifacts/evaluation/<benchmark_version>/   (공식 평가만)
    runs/finetune/<TAG>/ (KEEP 표시된 run 또는 --models로 고른 run)
                                                    → models/<TAG>/  +  configs/models/<TAG>.yaml (eval_config.yaml)
    runs/finetune/<TAG>/ 의 기록 파일(모든 run)       → results/finetune_runs/<TAG>/
                                                       (model_manifest.json, eval_config.yaml, notebook_code.py — 작은 텍스트)
    + 공식 평가마다 한 줄씩                          → results/experiments.csv  (실험 기록표, TAG 기준으로 갱신)

`results/experiments.csv`는 팀 실험 기록표다: 평가 하나당 한 줄(모델, 누가, NOTE, 학습 데이터 해시, GPU, 학습 precision,
평가 dtype, 라이브러리, 지표, 기준 대비 Δ·p, KEEP 여부). manifest와 평가 json에서 자동으로 채우므로 사람이 적을 필요가 없고,
이미 있는 줄은 같은 평가 TAG면 새 값으로 바뀐다(Drive에서 정리돼 지워진 run의 줄도 남는다). 모델 가중치(`models/`)는
.gitignore라 git에 안 올라가므로, 어떤 run이었는지는 `results/finetune_runs/<TAG>/model_manifest.json`으로 남긴다.

`--verify`: 가져온 평가 json마다 로컬 qrels + 가져온 run.csv로 **공식 evaluator를 다시 돌려** Colab에서 낸 지표와
같은지 확인한다(같은 함수라 같아야 정상 — 다르면 qrels 버전이 다른 것). 하나라도 다르면 종료코드 1.

사용법:
    # Drive의 store-search-ai 폴더를 내려받아(웹 Drive에서 폴더 다운로드 → 압축 해제) 그 경로를 준다
    python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --verify
    python scripts/import_colab_results.py --drive-dir ... --models bge_m3_ft_jisu_20261002_0512   # 특정 run만 모델 복사
    python scripts/import_colab_results.py --drive-dir ... --dry-run                               # 무엇을 옮길지만 출력

`models/`는 .gitignore 대상(용량)이고, results/·artifacts/·configs/models/<TAG>.yaml은 커밋할 수 있다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path, PureWindowsPath

import pandas as pd

from store_search_ai.pipeline.common import load_config


def _run_path(report: dict) -> PureWindowsPath:
    r"""report["run"](Colab에서는 /content/drive/..., 로컬에서는 C:\...)에서 run 파일 경로를 읽는다.

    PureWindowsPath는 / 와 \ 를 둘 다 구분자로 인식해서 어느 쪽에서 만든 report든 같은 방식으로 읽힌다.
    """

    return PureWindowsPath(report["run"])


def plan_import(drive_dir: Path, repo_root: Path, benchmark_version: str, models: list[str] | None) -> list[tuple[Path, Path]]:
    """(원본, 대상) 복사 목록. 비공식(official=false, smoke test 등) 평가와 그 run은 뺀다."""

    runs = drive_dir / "runs"
    plan: list[tuple[Path, Path]] = []

    unofficial_tags = set()
    eval_dir = runs / "evaluation"
    for path in sorted(eval_dir.glob("*_evaluation.json")) if eval_dir.exists() else []:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("official", True):
            unofficial_tags.add(_run_path(report).parent.name)
            continue
        target_dir = repo_root / "artifacts" / "evaluation" / benchmark_version
        plan.append((path, target_dir / path.name))
        per_query = path.with_name(path.name.replace("_evaluation.json", "_per_query.csv"))
        if per_query.exists():
            plan.append((per_query, target_dir / per_query.name))

    model_eval = runs / "model_eval"
    for tag_dir in sorted(model_eval.iterdir()) if model_eval.exists() else []:
        if tag_dir.is_dir() and tag_dir.name not in unofficial_tags:
            for run_file in sorted(tag_dir.glob("run_*.csv")):
                if not RUN_FILE_PATTERN.fullmatch(run_file.name):   # 손으로 만든 사본(run_..._pre.csv 등)은 안 가져옴
                    print(f"[건너뜀] 정식 run 파일 이름이 아님: {tag_dir.name}/{run_file.name}")
                    continue
                plan.append((run_file, repo_root / "results" / "model_eval" / tag_dir.name / run_file.name))

    finetune = runs / "finetune"
    if finetune.exists():
        for run_dir in sorted(finetune.iterdir()):
            if not run_dir.is_dir() or not (run_dir / "model_manifest.json").exists():
                continue
            for name in RECORD_FILES:   # 기록 파일은 KEEP과 상관없이 전부(작은 텍스트, git에 남김)
                if (run_dir / name).exists():
                    plan.append((run_dir / name, repo_root / "results" / "finetune_runs" / run_dir.name / name))
            chosen = run_dir.name in models if models else (run_dir / "KEEP").exists()
            if chosen:
                plan.append((run_dir, repo_root / "models" / run_dir.name))
                if (run_dir / "eval_config.yaml").exists():
                    plan.append((run_dir / "eval_config.yaml", repo_root / "configs" / "models" / f"{run_dir.name}.yaml"))
    return plan


RUN_FILE_PATTERN = re.compile(r"run_[a-z0-9_]+_(train|val|test)\.csv")
"""노트북 evaluate()가 쓰는 run 파일 이름(`run_<template>_<split>.csv`). 이 형식이 아닌 파일은 평가 json과 연결되지 않는다."""

RECORD_FILES = ("model_manifest.json", "eval_config.yaml", "notebook_code.py")

EXPERIMENT_COLUMNS = [
    "eval_tag", "model", "kind", "owner", "base_model", "note", "train_data_sha8", "gpu", "precision", "eval_dtype",
    "libs", "nDCG@10", "Judged@10", "Recall@100", "MRR@100", "Bpref", "delta_nDCG@10", "p_nDCG@10", "baseline",
    "keep", "evaluated_at",
]


def experiment_rows(drive_dir: Path, models: list[str] | None = None) -> list[dict]:
    """Drive runs/의 공식 평가마다 실험 기록표 한 줄(평가 json + 그 모델의 manifest)."""

    runs = drive_dir / "runs"
    eval_dir = runs / "evaluation"
    rows = []
    for path in sorted(eval_dir.glob("*_evaluation.json")) if eval_dir.exists() else []:
        report = json.loads(path.read_text(encoding="utf-8"))
        if not report.get("official", True):
            continue
        model = _run_path(report).parent.name
        run_dir = runs / "finetune" / model
        manifest_path = run_dir / "model_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
        aggregate = report.get("aggregate", {})
        ndcg = (report.get("comparison") or {}).get("metrics", {}).get("nDCG@10", {})
        libs = report.get("library_versions") or {}
        rows.append({
            "eval_tag": report["tag"],
            "model": model,
            "kind": "fine-tuned" if manifest else "zero-shot",
            "owner": manifest.get("owner"),
            "base_model": manifest.get("base_model_id") or report.get("model_id"),
            "note": (manifest.get("hyperparameters") or {}).get("note"),
            "train_data_sha8": ((manifest.get("training_data") or {}).get("sha256") or "")[:8] or None,
            "gpu": (manifest.get("environment") or {}).get("gpu"),
            "precision": manifest.get("precision"),
            "eval_dtype": report.get("eval_dtype"),
            "libs": f"st{libs.get('sentence-transformers')}/tf{libs.get('transformers')}" if libs else None,
            **{m: aggregate.get(m) for m in ("nDCG@10", "Judged@10", "Recall@100", "MRR@100", "Bpref")},
            "delta_nDCG@10": ndcg.get("delta_mean"),
            "p_nDCG@10": ndcg.get("paired_permutation_pvalue"),
            "baseline": (report.get("comparison") or {}).get("baseline_tag"),
            "keep": bool(manifest) and ((run_dir / "KEEP").exists() or model in (models or [])),
            "evaluated_at": report.get("evaluated_at"),
        })
    return rows


def update_experiment_registry(path: Path, rows: list[dict]) -> pd.DataFrame:
    """기존 기록표에 rows를 합친다(같은 eval_tag는 새 값으로 교체, 나머지 줄은 유지)."""

    new = pd.DataFrame(rows, columns=EXPERIMENT_COLUMNS)
    if path.exists():
        old = pd.read_csv(path, encoding="utf-8-sig")
        old = old[~old["eval_tag"].isin(new["eval_tag"])]
        new = pd.concat([old, new], ignore_index=True) if len(old) else new
    new = new.reindex(columns=EXPERIMENT_COLUMNS).sort_values(["eval_tag"]).reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    return new


def apply_plan(plan: list[tuple[Path, Path]]) -> None:
    for src, dst in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)


def verify_imported(repo_root: Path, benchmark_dir: Path, eval_files: list[Path], bootstrap: int, seed: int) -> list[str]:
    """가져온 평가 json마다 로컬에서 다시 채점해 aggregate가 같은지 본다. 다른 것의 설명 목록을 반환."""

    from store_search_ai.evaluation.evaluator import build_evaluation_report

    problems = []
    for path in eval_files:
        report = json.loads(path.read_text(encoding="utf-8"))
        colab_run = _run_path(report)
        local_run = repo_root / "results" / "model_eval" / colab_run.parent.name / colab_run.name
        split = colab_run.stem.rsplit("_", 1)[-1]
        if not local_run.exists():
            problems.append(f"{path.name}: run 파일 없음 {local_run}")
            continue
        local, _ = build_evaluation_report(
            qrels_path=benchmark_dir / f"qrels_{split}.trec", run_path=local_run, tag=report["tag"],
            bootstrap_samples=bootstrap, seed=seed,
        )
        diffs = {
            m: (report["aggregate"].get(m), v)
            for m, v in local["aggregate"].items()
            if abs((report["aggregate"].get(m) or 0) - v) > 1e-9
        }
        if diffs:
            problems.append(f"{path.name}: Colab과 로컬 지표가 다름 {diffs} — qrels 버전이 다른지 확인")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive-dir", required=True, help="내려받은 Drive의 store-search-ai 폴더(안에 runs/가 있음)")
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--models", nargs="*", default=None, help="models/로 복사할 run TAG(생략하면 KEEP 표시된 run)")
    parser.add_argument("--verify", action="store_true", help="가져온 평가를 로컬 공식 evaluator로 다시 채점해 비교")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo_root = Path.cwd()
    config = load_config(args.config)
    drive_dir = Path(args.drive_dir)
    if not (drive_dir / "runs").exists():
        raise SystemExit(f"{drive_dir}/runs 가 없습니다 — Drive의 store-search-ai 폴더를 내려받은 경로를 주세요.")

    plan = plan_import(drive_dir, repo_root, config["benchmark_version"], args.models)
    for src, dst in plan:
        print(f"{'[예정]' if args.dry_run else '[복사]'} {src}  →  {dst.relative_to(repo_root)}")
    rows = experiment_rows(drive_dir, args.models)
    registry = repo_root / "results" / "experiments.csv"
    if args.dry_run:
        print(f"[예정] {registry.relative_to(repo_root)}에 평가 {len(rows)}줄 기록")
        return
    apply_plan(plan)
    print(f"[완료] {len(plan)}개 항목 복사")
    table = update_experiment_registry(registry, rows)
    print(f"[기록] {registry.relative_to(repo_root)} — 평가 {len(rows)}줄 갱신(전체 {len(table)}줄)")

    if args.verify:
        eval_files = [dst for _, dst in plan if dst.name.endswith("_evaluation.json")]
        settings = config.get("evaluation", {})
        problems = verify_imported(
            repo_root, Path(config["benchmark_dir"]), eval_files,
            int(settings.get("bootstrap_samples", 10000)), int(settings.get("random_seed", 20260831)),
        )
        for problem in problems:
            print(f"[불일치] {problem}")
        if problems:
            raise SystemExit(1)
        print(f"[검증] 평가 {len(eval_files)}개 모두 로컬 공식 evaluator 결과와 일치")


if __name__ == "__main__":
    main()
