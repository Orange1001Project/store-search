"""모델 하나를 "인코딩 → exact 검색 → 공식 채점 → 저장 → manifest 기록"까지 한 번에 평가한다.

로컬(또는 `src/`를 쓰는 환경)에서 모델을 평가하고, `scripts/import_colab_results.py`·테스트가 같은 결과 형식을 쓰기 위한
함수다(Colab 노트북 `colab/train_eval.ipynb`는 같은 로직을 셀에 담고 있다 — `tests/test_train_eval_notebook.py`가
노트북 채점이 공식 evaluator와 같은지 확인). 채점은 `scripts/13_evaluate_run.py`와 **같은
함수**(`evaluator.build_evaluation_report`)로 하므로 Colab에서 본 점수와 로컬 13번의 점수는 같다
(`scripts/import_colab_results.py --verify`가 로컬에서 다시 채점해 확인한다).

결과 저장 위치(Colab에서는 Drive):
    run_root/<tag>/run_<template>_<split>.csv                  — 검색 결과(쿼리당 top-k)
    eval_root/<tag>_<template>_<split>_evaluation.json         — 지표·신뢰구간·(있으면) 기준 모델 대비 비교
    eval_root/<tag>_<template>_<split>_per_query.csv           — 쿼리별 지표
이름 규칙은 15번(`15_score_model_runs.py`)과 같아서 로컬로 가져오면 그대로 이어서 쓸 수 있다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from store_search_ai.common.hf_compat import library_versions
from store_search_ai.evaluation.evaluator import (
    METRIC_SPECS,
    build_evaluation_report,
    save_evaluation_outputs,
)
from store_search_ai.models.leaderboard import build_leaderboard
from store_search_ai.models.model_eval import TEMPLATE_COLUMNS
from store_search_ai.pipeline.common import (
    append_model_manifest_evaluation,
    load_active_queries,
    load_config,
)

BENCHMARK_CONFIG = Path("configs/benchmark/storesearch_ko_v1.yaml")


def evaluation_tag(tag: str, template: str, split: str) -> str:
    return f"{tag}_{template}_{split}"


def load_eval_inputs(project_dir: str | Path) -> dict:
    """저장소 루트(project_dir)에서 평가에 필요한 것을 읽는다: 벤치마크 설정, corpus, active queries."""

    project_dir = Path(project_dir)
    config = load_config(project_dir / BENCHMARK_CONFIG)
    corpus = pd.read_parquet(project_dir / config["corpus_path"])
    queries = load_active_queries(project_dir / config["benchmark_dir"])
    return {"config": config, "corpus": corpus, "queries": queries, "benchmark_dir": project_dir / config["benchmark_dir"]}


def evaluate_model(
    model_config: dict,
    inputs: dict,
    *,
    run_root: str | Path,
    eval_root: str | Path,
    split: str = "val",
    template: str = "t1_minimal",
    baseline_tag: str | None = None,
    allow_test: bool = False,
    official: bool = True,
    encoder=None,
    doc_embeddings=None,
    top_k: int = 100,
) -> dict:
    """`model_config`(configs/models/*.yaml 형식 dict)의 모델을 `split`으로 평가하고 결과를 저장한다.

    - test는 `allow_test=True`일 때만 돈다 — 모델·설정 선택은 val로 하고, test는 최종 후보를 정한 뒤 한 번만.
    - `baseline_tag`의 같은 split run이 `run_root`에 있으면 그 모델 대비 paired 비교(p-value)를 같이 계산한다.
    - `official=False`는 smoke test처럼 축소 코퍼스로 돌린 결과 — 리더보드에서 빠진다.
    - `encoder`/`doc_embeddings`를 넘기면 재사용한다(같은 모델의 prompt 변형끼리 문서 임베딩을 다시 안 만들기 위함).
    - 모델 폴더에 model_manifest.json이 있으면(fine-tuned 모델) 이번 평가를 `evaluations`에 추가한다.

    반환: {"report", "run_path", "evaluation_path", "encoder", "doc_embeddings"}
    """

    if split == "test" and not allow_test:
        raise ValueError(
            "test split은 최종 후보를 정한 뒤 한 번만 봅니다 — 정말 최종 평가라면 allow_test=True로 다시 실행하세요."
        )

    from store_search_ai.models.sentence_transformer_encoder import (
        SentenceTransformerEncoder,
    )
    from store_search_ai.retrieval.exact_search import ExactCosineSearch

    tag = model_config["name"]
    if encoder is None:
        encoder = SentenceTransformerEncoder(model_config)
    encoder.config = model_config  # 같은 모델 재사용 시 prompt 등 설정만 바꾼다

    corpus, queries, benchmark_config = inputs["corpus"], inputs["queries"], inputs["config"]
    split_queries = queries[queries["split"] == split].reset_index(drop=True)
    if doc_embeddings is None:
        documents = corpus[TEMPLATE_COLUMNS[template]].fillna("").astype(str).tolist()
        doc_embeddings = encoder.encode_corpus(documents)
    query_embeddings = encoder.encode_queries(split_queries["query"].astype(str).tolist())

    run = ExactCosineSearch(corpus_embeddings=doc_embeddings, doc_ids=corpus["doc_id"].tolist()).search(
        query_embeddings=query_embeddings,
        query_ids=split_queries["query_id"].tolist(),
        top_k=top_k,
        system=f"{tag}_{template}",
    )
    run_path = Path(run_root) / tag / f"run_{template}_{split}.csv"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run.to_csv(run_path, index=False, encoding="utf-8-sig", lineterminator="\n")

    baseline_run = Path(run_root) / baseline_tag / run_path.name if baseline_tag and baseline_tag != tag else None
    if baseline_run is not None and not baseline_run.exists():
        print(f"[안내] 기준 모델 run이 없어 비교를 건너뜀: {baseline_run}")
        baseline_run = None

    eval_settings = benchmark_config.get("evaluation", {})
    etag = evaluation_tag(tag, template, split)
    report, per_query = build_evaluation_report(
        qrels_path=inputs["benchmark_dir"] / f"qrels_{split}.trec",
        run_path=run_path,
        tag=etag,
        bootstrap_samples=int(eval_settings.get("bootstrap_samples", 10000)),
        seed=int(eval_settings.get("random_seed", 20260831)),
        compare_run_path=baseline_run,
        compare_tag=baseline_tag or "baseline",
    )
    report["official"] = official
    report["corpus_docs"] = len(corpus)
    report["model_id"] = str(model_config["model_id"])
    report["evaluated_at"] = datetime.now(UTC).isoformat()
    report["library_versions"] = library_versions()  # 비교는 같은 라이브러리 버전끼리(hf_compat 참고)
    _, evaluation_path = save_evaluation_outputs(report, per_query, Path(eval_root), etag)

    model_dir = Path(str(model_config["model_id"]))
    if model_dir.is_dir() and (model_dir / "model_manifest.json").exists():
        append_model_manifest_evaluation(
            model_dir,
            {
                "evaluated_at": report["evaluated_at"],
                "split": split,
                "template": template,
                "tag": etag,
                "official": official,
                "metrics": report["aggregate"],
                "baseline": report.get("comparison", {}).get("baseline_tag"),
                "where": "colab",
            },
        )

    return {
        "report": report,
        "run_path": run_path,
        "evaluation_path": evaluation_path,
        "encoder": encoder,
        "doc_embeddings": doc_embeddings,
    }


def format_report(report: dict, metrics: tuple[str, ...] = ("nDCG@10", "Judged@10", "Recall@100", "MRR@100")) -> str:
    """노트북에 찍을 짧은 요약(지표 + 95% CI + 기준 모델 대비)."""

    lines = [f"[{report['tag']}]  queries={report['query_count']}  corpus={report.get('corpus_docs')}"
             + ("" if report.get("official", True) else "  (비공식: 축소 코퍼스)")]
    for metric in metrics:
        value = report["aggregate"].get(metric)
        ci = report.get("query_bootstrap_ci95", {}).get(metric, {}).get("ci95")
        if value is not None:
            lines.append(f"  {metric:<11} {value:.4f}" + (f"  [95% CI {ci[0]:.4f}, {ci[1]:.4f}]" if ci else ""))
    comparison = report.get("comparison")
    if comparison:
        lines.append(f"  vs {comparison['baseline_tag']}:")
        for metric in metrics:
            result = comparison["metrics"].get(metric)
            if result:
                lines.append(
                    f"    {metric:<11} Δ={result['delta_mean']:+.4f}  p={result['paired_permutation_pvalue']:.4f}  "
                    f"wins/ties/losses={result['wins']}/{result['ties']}/{result['losses']}"
                )
    return "\n".join(lines)


def collect_leaderboard(eval_root: str | Path, split: str = "val", include_unofficial: bool = False) -> pd.DataFrame:
    """eval_root의 `*_<split>_evaluation.json`을 모아 nDCG@10 순 리더보드로 만든다(기준 모델 대비 Δ·p 포함)."""

    rows = []
    for path in sorted(Path(eval_root).glob(f"*_{split}_evaluation.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not include_unofficial and not report.get("official", True):
            continue
        row = {"tag": report["tag"], **{m: report["aggregate"].get(m) for m in METRIC_SPECS}}
        libs = report.get("library_versions") or {}
        if libs:
            # 비교는 같은 라이브러리 버전끼리 — Colab 기본 패키지가 바뀌면 이 칸이 달라진다
            row["libs"] = f"st{libs.get('sentence-transformers')}/tf{libs.get('transformers')}"
        comparison = report.get("comparison")
        if comparison:
            ndcg = comparison["metrics"].get("nDCG@10", {})
            row["baseline"] = comparison["baseline_tag"]
            row["ΔnDCG@10"] = ndcg.get("delta_mean")
            row["p(nDCG@10)"] = ndcg.get("paired_permutation_pvalue")
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return build_leaderboard(rows)
