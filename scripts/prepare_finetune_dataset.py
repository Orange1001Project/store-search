"""qrels_train + queries.csv + corpus로부터 임베딩 모델 fine-tuning용 학습쌍을 만든다.

파이프라인 번호가 없는 이유: 01~15 실행 순서와 무관하게, train qrels가 준비된 뒤
(`docs/PIPELINE.md` 4절, `09_prepare_full_annotations.py`가 만드는
`qrels/provisional_v1/qrels_train_provisional.csv` 또는 `11_build_qrels.py`가 만드는
최종 `qrels_train.csv`) 필요할 때마다 로컬(GPU 불필요)에서 실행하는 데이터 준비 도구다.
결과 jsonl을 Colab으로 올려서 `colab/run_finetune_*.py`가 그대로 읽는다.

만드는 방식(왜 in-batch negative만 쓰지 않는가):
  query 하나당 (a) positive = 그 query의 candidate pool에서 relevance >= binary_relevance_threshold
  (기본 2)인 문서, (b) negatives = **같은 query의 같은 pool**에서 relevance가 그 미만인 문서를
  최대 --max-negatives개 뽑는다(경계 사례 relevance=1을 relevance=0보다 우선 — 더 어려운
  negative가 학습에 유리하다는 GPL/E5/BGE 계열 논문들의 hard negative mining과 같은 발상).
  이러면 무작위 in-batch negative보다 "그 쿼리와 어휘적으로 비슷해 보이지만 실제로는 관련 없는"
  진짜 어려운 negative를 쓸 수 있다 — pooling(06~07)이 이미 그런 후보를 모아 놨고, train qrels가
  그 전체 pool에 대한 사람 판정이므로 추가 검색 없이 바로 재사용 가능하다.

출력 스키마(jsonl, 한 줄 = 쿼리 하나):
  {"query_id": "...", "query": "...", "positive": "...", "negatives": ["...", ...]}

이 스키마는 프레임워크 중립적이다 — ms-swift는 positive->response, negatives->rejected_response로
매핑해서 쓰고, sentence-transformers는 InputExample(texts=[query, positive, *negatives])로 그대로 쓴다.
positive가 없는 query(=pool 전체가 0/1로만 판정됨)는 학습쌍을 만들 수 없으므로 제외한다.

사용법:
    python scripts/prepare_finetune_dataset.py
    python scripts/prepare_finetune_dataset.py --qrels benchmark/storesearch_ko_v1/qrels_train.csv \
        --output data/finetune/train_pairs_v1.jsonl --max-negatives 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_active_queries, load_config

TEMPLATE_COLUMNS = {
    "t1_minimal": "search_text_t1_minimal",
    "t2_market": "search_text_t2_market",
    "t3_market_type": "search_text_t3_market_type",
}


def resolve_train_qrels_path(benchmark_dir: Path) -> Path:
    final_path = benchmark_dir / "qrels_train.csv"
    if final_path.exists():
        return final_path
    provisional_path = benchmark_dir / "qrels" / "provisional_v1" / "qrels_train_provisional.csv"
    if provisional_path.exists():
        return provisional_path
    raise SystemExit(
        f"train qrels를 찾을 수 없습니다: {final_path} 또는 {provisional_path}. "
        "docs/PIPELINE.md 4절(08_make_full_annotation_sheets.py -> 사람이 채움 -> "
        "09_prepare_full_annotations.py)을 먼저 진행하세요."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument(
        "--qrels",
        default=None,
        help="기본값: qrels_train.csv(최종)가 있으면 그것, 없으면 provisional_v1 사용",
    )
    parser.add_argument("--template", choices=list(TEMPLATE_COLUMNS), default="t1_minimal")
    parser.add_argument("--max-negatives", type=int, default=8)
    parser.add_argument("--output", default="data/finetune/train_pairs.jsonl")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    threshold = int(config["evaluation"]["binary_relevance_threshold"])

    qrels_path = Path(args.qrels) if args.qrels else resolve_train_qrels_path(benchmark_dir)
    print(f"[INFO] train qrels: {qrels_path}")

    qrels = pd.read_csv(qrels_path, encoding="utf-8-sig")
    queries = load_active_queries(benchmark_dir)
    queries = queries[queries["split"] == "train"].set_index("query_id")

    corpus = pd.read_parquet(config["corpus_path"])
    text_col = TEMPLATE_COLUMNS[args.template]
    doc_text = corpus.set_index("doc_id")[text_col].fillna("").astype(str)

    qrels = qrels[qrels["query_id"].isin(queries.index) & qrels["doc_id"].isin(doc_text.index)]

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_written = 0
    n_skipped_no_positive = 0
    total_negatives = 0

    with output_path.open("w", encoding="utf-8") as f:
        for query_id, group in qrels.groupby("query_id"):
            positives = group[group["relevance"] >= threshold]["doc_id"].tolist()
            if not positives:
                n_skipped_no_positive += 1
                continue

            negatives_df = group[group["relevance"] < threshold].copy()
            # relevance=1(경계 사례)을 relevance=0보다 먼저 써서 더 어려운 negative를 우선한다.
            negatives_df = negatives_df.sort_values("relevance", ascending=False)
            negatives = negatives_df["doc_id"].tolist()[: args.max_negatives]

            record = {
                "query_id": query_id,
                "query": str(queries.loc[query_id, "query"]),
                "positive": doc_text[positives[0]],
                "negatives": [doc_text[doc_id] for doc_id in negatives],
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            n_written += 1
            total_negatives += len(negatives)

    print(
        f"[완료] {output_path}: query {n_written}개 "
        f"(평균 negative {total_negatives / max(n_written, 1):.1f}개/query)"
    )
    print(f"[제외] positive 없는 query {n_skipped_no_positive}개 (pool 전체가 relevance<{threshold})")


if __name__ == "__main__":
    main()
