"""qrels_train + queries.csv + corpus로부터 임베딩 모델 fine-tuning용 학습쌍을 만든다.

파이프라인 번호가 없는 이유: 01~15 실행 순서와 무관하게, train qrels가 준비된 뒤
(`docs/PIPELINE.md` 4절, `09_prepare_full_annotations.py`가 만드는
`qrels/{round}/qrels_train_provisional.csv` 또는 `11_build_qrels.py`가 만드는
최종 `qrels_train.csv`) 필요할 때마다 로컬(GPU 불필요)에서 실행하는 데이터 준비 도구다.
결과 jsonl은 `scripts/pack_for_colab.py`로 Drive `data/`에 올려 `colab/train_eval.ipynb`가 그대로 읽는다.

핵심 로직은 src/store_search_ai/data/finetune_dataset.py에 있다. 이 스크립트는 인자 파싱,
파일 IO, 콘솔 출력만 담당한다.

출력 스키마(jsonl, 한 줄 = 쿼리 하나):
  {"query_id": "...", "query": "...", "positives": ["...", ...], "negatives": ["...", ...]}

jsonl 옆에 `<이름>.meta.json`도 함께 쓴다(어떤 qrels/설정/커밋으로 만든 학습 데이터인지).
Colab 학습 스크립트가 이 파일을 그대로 model_manifest.json의 training_data에 복사한다 —
jsonl만으로는 provisional qrels로 만든 건지 final로 만든 건지 나중에 구분할 수 없기 때문.

사용법:
    python scripts/prepare_finetune_dataset.py
    python scripts/prepare_finetune_dataset.py --qrels benchmark/storesearch_ko_v1/qrels_train.csv \
        --output data/finetune/train_pairs_v1.jsonl --max-negatives 8
"""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from store_search_ai.data.finetune_dataset import (
    TEMPLATE_COLUMNS,
    build_training_pairs,
    resolve_train_qrels_path,
)
from store_search_ai.pipeline.common import (
    DEFAULT_ANNOTATION_ROUND,
    load_active_queries,
    load_config,
    sha256_file,
)


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument(
        "--qrels", default=None, help="기본값: qrels_train.csv(최종)가 있으면 그것, 없으면 qrels/{round}/ 밑 provisional 사용"
    )
    parser.add_argument(
        "--round",
        default=DEFAULT_ANNOTATION_ROUND,
        help="--qrels를 안 줬을 때 provisional qrels를 찾을 애노테이션 라운드(09번과 동일 값)",
    )
    parser.add_argument("--template", choices=list(TEMPLATE_COLUMNS), default="t1_minimal")
    parser.add_argument("--max-negatives", type=int, default=8)
    parser.add_argument("--output", default="data/finetune/train_pairs.jsonl")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    threshold = int(config["evaluation"]["binary_relevance_threshold"])

    qrels_path = Path(args.qrels) if args.qrels else resolve_train_qrels_path(benchmark_dir, args.round)
    print(f"[INFO] train qrels: {qrels_path}")

    qrels = pd.read_csv(qrels_path, encoding="utf-8-sig")
    queries = load_active_queries(benchmark_dir)
    queries = queries[queries["split"] == "train"].set_index("query_id")

    corpus = pd.read_parquet(config["corpus_path"])
    text_col = TEMPLATE_COLUMNS[args.template]
    doc_text = corpus.set_index("doc_id")[text_col].fillna("").astype(str)

    qrels = qrels[qrels["query_id"].isin(queries.index) & qrels["doc_id"].isin(doc_text.index)]

    records, stats = build_training_pairs(
        qrels, queries, doc_text, threshold=threshold, max_negatives=args.max_negatives
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    meta_path = output_path.with_suffix(".meta.json")
    meta = {
        "created_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "benchmark_version": config["benchmark_version"],
        "corpus_version": config["corpus_version"],
        "qrels_path": qrels_path.as_posix(),
        "qrels_sha256": sha256_file(qrels_path),
        "qrels_kind": "final" if qrels_path.name == "qrels_train.csv" else "provisional",
        "template": args.template,
        "binary_relevance_threshold": threshold,
        "max_negatives": args.max_negatives,
        "train_pairs_sha256": sha256_file(output_path),
        "stats": stats,
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

    n_written = stats["n_written"]
    print(
        f"[완료] {output_path}: query {n_written}개 "
        f"(평균 positive {stats['total_positives'] / max(n_written, 1):.1f}개, "
        f"negative {stats['total_negatives'] / max(n_written, 1):.1f}개/query)"
    )
    print(f"[완료] {meta_path} (Colab에 jsonl과 같이 올릴 것)")
    print(f"[제외] positive 없는 query {stats['n_skipped_no_positive']}개 (pool 전체가 relevance<{threshold})")


if __name__ == "__main__":
    main()
