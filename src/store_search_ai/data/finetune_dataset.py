"""qrels_train + queries.csv + corpus로부터 임베딩 모델 fine-tuning용 학습쌍을 만드는 로직.

scripts/prepare_finetune_dataset.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심
로직 전체 (docs/PIPELINE_CODE_REFERENCE.md `prepare_finetune_dataset.py` 절 참고).

query 하나당 (a) positive = 그 query의 candidate pool에서 relevance >= binary_relevance_threshold
인 문서, (b) negatives = 같은 query의 같은 pool에서 relevance가 그 미만인 문서를 최대
max_negatives개 뽑는다(경계 사례 relevance=1을 relevance=0보다 우선 — 더 어려운 negative가
학습에 유리하다는 GPL/E5/BGE 계열 논문들의 hard negative mining과 같은 발상). positive가 없는
query(=pool 전체가 0/1로만 판정됨)는 학습쌍을 만들 수 없으므로 제외한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

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


def build_training_pairs(
    qrels: pd.DataFrame,
    queries: pd.DataFrame,
    doc_text: pd.Series,
    threshold: int,
    max_negatives: int,
) -> tuple[list[dict], dict]:
    """(query, positive, negatives) 레코드 리스트와 요약 통계를 반환한다.

    `queries`는 query_id로 인덱싱된 train split의 active queries, `doc_text`는 doc_id로
    인덱싱된 corpus 텍스트 컬럼이어야 한다. `qrels`는 이미 두 인덱스에 존재하는 행만으로
    필터링돼 있어야 한다(스크립트에서 미리 처리).
    """

    records = []
    n_skipped_no_positive = 0
    total_negatives = 0

    for query_id, group in qrels.groupby("query_id"):
        positives = group[group["relevance"] >= threshold]["doc_id"].tolist()
        if not positives:
            n_skipped_no_positive += 1
            continue

        negatives_df = group[group["relevance"] < threshold].copy()
        # relevance=1(경계 사례)을 relevance=0보다 먼저 써서 더 어려운 negative를 우선한다.
        negatives_df = negatives_df.sort_values("relevance", ascending=False)
        negatives = negatives_df["doc_id"].tolist()[:max_negatives]

        records.append(
            {
                "query_id": query_id,
                "query": str(queries.loc[query_id, "query"]),
                "positive": doc_text[positives[0]],
                "negatives": [doc_text[doc_id] for doc_id in negatives],
            }
        )
        total_negatives += len(negatives)

    stats = {
        "n_written": len(records),
        "n_skipped_no_positive": n_skipped_no_positive,
        "total_negatives": total_negatives,
    }
    return records, stats
