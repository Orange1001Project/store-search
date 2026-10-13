"""qrels_train + queries.csv + corpus로부터 임베딩 모델 fine-tuning용 학습쌍을 만드는 로직.

scripts/prepare_finetune_dataset.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심
로직 전체 (docs/PIPELINE_CODE_REFERENCE.md `prepare_finetune_dataset.py` 절 참고).

query 하나당 (a) positives = 그 query의 candidate pool에서 relevance >= binary_relevance_threshold
인 문서 **전부**(relevance 높은 순), (b) negatives = 같은 query의 같은 pool에서
relevance가 그 미만인 문서를 최대 max_negatives개 뽑는다(경계 사례 relevance=1을 relevance=0보다
우선 — 더 어려운 negative가 학습에 유리하다는 GPL/E5/BGE 계열 논문들의 hard negative mining과 같은
발상). positive가 없는 query(=pool 전체가 0/1로만 판정됨)는 학습쌍을 만들 수 없으므로 제외한다.

예전에는 positive를 query당 첫 번째 하나만 썼다 — train query가 237개뿐이라 학습 예시도 237개
(batch 16 x 3 epoch = 약 45 step)밖에 안 됐고, 사람이 판정한 나머지 positive는 전부 버려졌다.
지금은 positive 목록을 전부 jsonl에 남기고, (query, positive) 행으로 펼치고 query당 개수를
자르는 건 학습 쪽(`store_search_ai.training.finetune.expand_training_rows`)에서 한다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

TEMPLATE_COLUMNS = {
    "t1_minimal": "search_text_t1_minimal",
    "t2_market": "search_text_t2_market",
    "t3_market_type": "search_text_t3_market_type",
}


def resolve_train_qrels_path(benchmark_dir: Path, round_name: str) -> Path:
    final_path = benchmark_dir / "qrels_train.csv"
    if final_path.exists():
        return final_path
    provisional_path = benchmark_dir / "qrels" / round_name / "qrels_train_provisional.csv"
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
    total_positives = 0
    total_negatives = 0

    for query_id, group in qrels.groupby("query_id"):
        # relevance=3을 2보다 먼저 — 학습 쪽에서 query당 positive 수를 자를 때 더 확실한 정답이 남도록.
        # kind="stable"이라 같은 relevance 안에서는 qrels 원래 순서가 유지된다(결정적).
        positives_df = group[group["relevance"] >= threshold].sort_values(
            "relevance", ascending=False, kind="stable"
        )
        # 학습은 doc_id가 아니라 텍스트를 본다 — 체인점처럼 텍스트가 완전히 같은 문서가 여럿이면
        # 한 번만 쓰고, positive와 텍스트가 같은 문서는 negative에서 뺀다(같은 텍스트를 정답이자
        # 오답으로 동시에 학습시키는 모순 방지).
        positives = list(dict.fromkeys(doc_text[doc_id] for doc_id in positives_df["doc_id"]))
        if not positives:
            n_skipped_no_positive += 1
            continue

        negatives_df = group[group["relevance"] < threshold].copy()
        # relevance=1(경계 사례)을 relevance=0보다 먼저 써서 더 어려운 negative를 우선한다.
        negatives_df = negatives_df.sort_values("relevance", ascending=False, kind="stable")
        positive_texts = set(positives)
        negative_texts = dict.fromkeys(doc_text[doc_id] for doc_id in negatives_df["doc_id"])
        negatives = [text for text in negative_texts if text not in positive_texts][:max_negatives]

        records.append(
            {
                "query_id": query_id,
                "query": str(queries.loc[query_id, "query"]),
                "positives": positives,
                "negatives": negatives,
            }
        )
        total_positives += len(positives)
        total_negatives += len(negatives)

    stats = {
        "n_written": len(records),
        "n_skipped_no_positive": n_skipped_no_positive,
        "total_positives": total_positives,
        "total_negatives": total_negatives,
    }
    return records, stats
