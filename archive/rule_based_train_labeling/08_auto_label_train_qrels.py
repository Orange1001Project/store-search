"""Train split qrels를 규칙 기반으로 자동 생성한다 (weak / distant supervision).

Calibration(과거 08~10) + train 사람 애노테이션 없이, 07_build_annotation_pool.py가
이미 만들어 둔 candidate_pool_internal.csv의 provenance만으로 train qrels를 만든다.
Pool의 각 (query_id, doc_id)에는 어떤 채널(run:*, target:positive:*, target:boundary:*,
random)로 후보가 됐는지가 이미 기록되어 있다 — 그 중 targeted term-match 채널이
바로 query family 정의(positive_terms/boundary_terms)와의 규칙 매칭 결과이므로,
그대로 relevance로 변환하면 된다:

  - target:positive:* 채널이 하나라도 있으면 → relevance=3 (직접 관련)
  - positive는 없고 target:boundary:* 채널이 있으면 → relevance=1 (경계 사례)
  - 둘 다 없으면(=lexical run/random 채널로만 pool에 들어옴) → relevance=0
    (TREC 관례대로, pooled-but-non-relevant 문서도 명시적으로 0으로 남겨
    학습 시 hard negative로 쓸 수 있게 한다)

이 방식은 GPL/E5/BGE/Qwen3-Embedding 등 dense retrieval 논문들이 대규모 학습
데이터를 만들 때 쓰는 weak/distant supervision과 동일한 발상이다. Val/Test는
여전히 사람이 이중 라벨링 + adjudication한 gold를 쓴다(09~11번 스크립트).

이 스크립트가 만드는 파일은 기존 12_build_qrels.py의 `--train-qrels` 기본값과
동일한 경로/스키마를 쓰므로, 뒤 단계 스크립트를 수정할 필요가 없다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config, write_trec_qrels


def parse_pool_sources(value: object) -> dict:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {}
    return json.loads(str(value))


def label_relevance(pool_sources_json: object) -> int:
    sources = parse_pool_sources(pool_sources_json)

    has_positive = any(
        key.startswith("target:positive:") for key in sources
    )
    if has_positive:
        return 3

    has_boundary = any(
        key.startswith("target:boundary:") for key in sources
    )
    if has_boundary:
        return 1

    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="configs/benchmark/storesearch_ko_v1.yaml",
    )
    parser.add_argument(
        "--output",
        default=(
            "benchmark/storesearch_ko_v1/"
            "qrels/provisional_v1/qrels_train_provisional.csv"
        ),
        help="12_build_qrels.py --train-qrels 기본값과 동일한 경로",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    if not pool_path.exists():
        raise FileNotFoundError(
            f"{pool_path} 가 없습니다. "
            "먼저 06_generate_lexical_runs.py, 07_build_annotation_pool.py를 실행하세요."
        )

    pool = pd.read_csv(pool_path)

    train_pool = pool[pool["split"] == "train"].copy()
    if train_pool.empty:
        raise ValueError(
            "candidate_pool_internal.csv에 split=train 후보가 없습니다."
        )

    train_pool["relevance"] = train_pool["pool_sources_json"].map(label_relevance)

    qrels = (
        train_pool[["query_id", "doc_id", "relevance", "query_family"]]
        .drop_duplicates(["query_id", "doc_id"])
        .sort_values(["query_id", "doc_id"])
        .reset_index(drop=True)
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    qrels.to_csv(output_path, index=False, encoding="utf-8-sig")
    write_trec_qrels(qrels, output_path.with_suffix(".trec"))

    grade_distribution = {
        str(int(k)): int(v)
        for k, v in qrels["relevance"].value_counts().sort_index().items()
    }

    summary = {
        "benchmark_status": "PROVISIONAL",
        "label_source": "rule_based_weak_supervision",
        "rule": {
            3: "matched a query family positive_term",
            1: "matched a query family boundary_term (and no positive_term match)",
            0: "pooled via lexical run / random channel only, no term match",
        },
        "queries": int(qrels["query_id"].nunique()),
        "judgments": int(len(qrels)),
        "grade_distribution": grade_distribution,
        "output": str(output_path),
        "important": (
            "This is a silver/weak-labeled qrels file for TRAIN only. "
            "It is not human-adjudicated gold. Val/Test remain human double-annotated "
            "(scripts/09~11)."
        ),
    }

    print("========== TRAIN QRELS AUTO-LABELED ==========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
