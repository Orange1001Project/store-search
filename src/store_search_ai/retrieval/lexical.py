"""사람 개입 없이, 서로 다른 lexical(어휘 기반) retrieval 시스템으로 각 쿼리의 top-k 후보를
뽑아 pooling 재료를 만드는 로직.

scripts/06_generate_lexical_runs.py의 CLI 배관(인자 파싱, 콘솔 출력)을 제외한 핵심 로직
전체 — 문서 텍스트 정규화/토큰화, char TF-IDF/word TF-IDF/BM25 세 시스템의 fit과 채점,
run 조립, manifest 생성까지 (docs/PIPELINE_CODE_REFERENCE.md `06_generate_lexical_runs.py`
절 참고).

세 시스템 모두 **query 텍스트만** 사용한다 — positive_terms/boundary_terms는 여기서 전혀
retrieval score에 영향을 주지 않는다(07_build_annotation_pool.py의 targeted 채널에서만
쓰임).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

ScoreFn = Callable[[str], np.ndarray]


def normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def tokenize(value: object) -> list[str]:
    return TOKEN_RE.findall(normalize_text(value).casefold())


def build_pool_document_texts(corpus: pd.DataFrame) -> pd.Series:
    """Pool discovery 전용 문서 텍스트(가맹점명 + 취급품목). 실제 모델 평가의 T1/T2/T3
    템플릿과는 별개다.
    """

    return (
        corpus["store_name"].fillna("").map(normalize_text)
        + " "
        + corpus["item_text"].fillna("").map(normalize_text)
    ).str.strip()


def fit_char_tfidf_scorer(docs: pd.Series) -> ScoreFn:
    vec = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 5), min_df=1, sublinear_tf=True, max_features=150000
    )
    mat = vec.fit_transform(docs)

    def score(query: str) -> np.ndarray:
        return (vec.transform([query]) @ mat.T).toarray()[0]

    return score


def fit_word_tfidf_scorer(docs: pd.Series) -> ScoreFn:
    vec = TfidfVectorizer(
        analyzer="word", ngram_range=(1, 2), token_pattern=r"(?u)\b\w+\b", min_df=1, sublinear_tf=True
    )
    mat = vec.fit_transform(docs)

    def score(query: str) -> np.ndarray:
        return (vec.transform([query]) @ mat.T).toarray()[0]

    return score


def fit_bm25_scorer(docs: pd.Series) -> ScoreFn:
    bm25 = BM25Okapi([tokenize(x) for x in docs.tolist()])

    def score(query: str) -> np.ndarray:
        return np.asarray(bm25.get_scores(tokenize(query)), dtype=float)

    return score


def retrieve_run(
    system: str,
    queries: pd.DataFrame,
    corpus: pd.DataFrame,
    score_fn: ScoreFn,
    top_k: int,
) -> tuple[pd.DataFrame, dict]:
    """쿼리별로 score_fn을 돌려 top-k run을 만든다.

    중요: score <= 0인 문서는 retrieval 결과로 기록하지 않는다 — lexical overlap이 전혀
    없는 query에서는 BM25/TF-IDF score가 전부 0이 될 수 있는데, 이 상태에서 강제로
    top-k를 채우면 임의 document가 retrieval result처럼 들어가 annotation pool을
    오염시킨다. random negative는 07_build_annotation_pool.py가 별도 채널에서 뽑는다.
    """

    rows = []
    query_with_results = 0
    query_without_results = 0
    result_counts = []

    for q in queries.itertuples(index=False):
        scores = np.asarray(score_fn(q.query), dtype=float)

        valid_indices = np.flatnonzero(np.isfinite(scores) & (scores > 0))
        if len(valid_indices) == 0:
            query_without_results += 1
            result_counts.append(0)
            continue

        ranked_indices = valid_indices[np.argsort(-scores[valid_indices])]
        ranked_indices = ranked_indices[:top_k]

        query_with_results += 1
        result_counts.append(len(ranked_indices))

        for rank, idx in enumerate(ranked_indices, start=1):
            rows.append(
                {
                    "query_id": q.query_id,
                    "doc_id": corpus.iloc[idx]["doc_id"],
                    "rank": rank,
                    "score": float(scores[idx]),
                    "system": system,
                }
            )

    run = pd.DataFrame(rows, columns=["query_id", "doc_id", "rank", "score", "system"])

    stats = {
        "system": system,
        "queries": len(queries),
        "queries_with_results": int(query_with_results),
        "queries_without_results": int(query_without_results),
        "run_rows": len(run),
        "mean_results_per_query": float(np.mean(result_counts)) if result_counts else 0.0,
        "max_results_per_query": int(max(result_counts)) if result_counts else 0,
        "zero_or_negative_score_rows": int((run["score"] <= 0).sum()) if len(run) else 0,
    }

    return run, stats


def write_run_files(run: pd.DataFrame, system: str, output_dir: Path) -> tuple[Path, Path]:
    """run을 {system}.csv/.trec로 저장하고 (csv_path, trec_path)를 반환한다."""

    csv_path = output_dir / f"{system}.csv"
    run.to_csv(csv_path, index=False, encoding="utf-8-sig")

    trec_path = output_dir / f"{system}.trec"
    with trec_path.open("w", encoding="utf-8") as f:
        for r in run.itertuples(index=False):
            f.write(f"{r.query_id} Q0 {r.doc_id} {r.rank} {r.score:.12f} {system}\n")

    return csv_path, trec_path


def build_lexical_run_manifest(run_depth: int, systems: list[str], run_stats: list[dict]) -> dict:
    return {
        "run_depth": run_depth,
        "systems": systems,
        "pool_text_fields": ["store_name", "item_text"],
        "run_stats": run_stats,
        "important": "Pooling runs use query text only; positive/boundary terms never alter retrieval scores.",
    }
