"""Qdrant 등 ANN vector DB를 붙이기 전 단계의 정확(exact) 코사인 검색.

BEIR의 `DenseRetrievalExactSearch`와 동일한 역할이다: 후보 모델을 비교하는 단계에서는
ANN 근사오차를 배제하고 "임베딩 자체의 품질"만 보고 싶기 때문에, 작은 corpus(13k~수십만
문서 수준)에서는 정확 코사인 유사도로 전수 비교한다. 서비스 규모가 커져서 exact search가
느려지면 이 클래스의 인터페이스(코퍼스 임베딩 + 쿼리 임베딩 → run)는 그대로 두고 내부
구현만 Qdrant/FAISS 같은 ANN 인덱스로 교체하면 된다 — 호출부(모델 평가 스크립트,
서빙 코드)는 바뀌지 않는다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


class ExactCosineSearch:
    def __init__(self, corpus_embeddings: np.ndarray, doc_ids: list[str]):
        if len(doc_ids) != corpus_embeddings.shape[0]:
            raise ValueError(
                "corpus_embeddings row count must match len(doc_ids): "
                f"{corpus_embeddings.shape[0]} != {len(doc_ids)}"
            )
        self.corpus_embeddings = corpus_embeddings.astype("float32")
        self.doc_ids = list(doc_ids)

    def search(
        self,
        query_embeddings: np.ndarray,
        query_ids: list[str],
        top_k: int,
        system: str,
    ) -> pd.DataFrame:
        """query_embeddings(정규화되어 있다고 가정) x corpus를 전수 비교해 top-k run을 만든다.

        반환 스키마는 공식 evaluator(`scripts/13_evaluate_run.py`)가 요구하는
        `query_id,doc_id,rank,score,system`과 동일하다.
        """

        if len(query_ids) != query_embeddings.shape[0]:
            raise ValueError(
                "query_embeddings row count must match len(query_ids): "
                f"{query_embeddings.shape[0]} != {len(query_ids)}"
            )

        top_k = min(top_k, len(self.doc_ids))
        scores = query_embeddings.astype("float32") @ self.corpus_embeddings.T

        rows = []
        for row_idx, query_id in enumerate(query_ids):
            row_scores = scores[row_idx]
            top_idx = np.argpartition(-row_scores, top_k - 1)[:top_k]
            top_idx = top_idx[np.argsort(-row_scores[top_idx])]
            for rank, doc_idx in enumerate(top_idx, start=1):
                rows.append(
                    {
                        "query_id": query_id,
                        "doc_id": self.doc_ids[doc_idx],
                        "rank": rank,
                        "score": float(row_scores[doc_idx]),
                        "system": system,
                    }
                )

        return pd.DataFrame(
            rows,
            columns=["query_id", "doc_id", "rank", "score", "system"],
        )
