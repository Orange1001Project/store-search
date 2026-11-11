"""LLM 쿼리 확장(X8, docs/archive/SERVICE_PIPELINE_PLAN.md 11-17·11-18).

업종·상황 쿼리마다 LLM이 만든 '찾는 가게 종류·품목' 키워드(Query2doc, Wang et al. EMNLP 2023; HyDE, Gao et al. ACL 2023)로
범위 안 가맹점을 문자 BM25 채점하고, 사례 안 최댓값으로 나눈 값 × w를 1단계 점수에 더한다. 1단계에 없던 가게는 확장 상위
DEPTH개까지 후보에 더한다(1단계 점수는 사례 최솟값에서 시작). 상호·브랜드 쿼리에는 쓰지 않는다 — 찾는 가게를 이미 안다.
서비스에서는 확장어를 미리 만들어 캐시한다(실시간 LLM 호출 없음).
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer

from store_search_ai.retrieval.fusion import _rerank
from store_search_ai.retrieval.lexical import char_ngrams

K1, B = 1.5, 0.75         # BM25Okapi 기본값(rank_bm25와 같음)
DEPTH = 200               # 사례마다 확장 점수 상위 몇 개를 쓸지(1단계에 없던 가게는 후보에 더함 — 11-17 dev에서 잰 구성)


class SparseBM25:
    """char n-gram BM25(`lexical.fit_bm25_scorer`와 같은 토큰·식, idf는 음수를 0으로)를 희소 행렬로 — 21만 곳 색인에서 후보만 빠르게 채점."""

    def __init__(self, docs: pd.Series):
        self.vec = CountVectorizer(analyzer=char_ngrams)
        tf = self.vec.fit_transform(docs.tolist()).tocsc().astype(np.float32)
        n = tf.shape[0]
        df = np.diff(tf.indptr)
        self.idf = np.maximum(np.log((n - df + 0.5) / (df + 0.5)), 0.0)
        dl = np.asarray(tf.sum(axis=1)).ravel()
        self.norm = K1 * (1 - B + B * dl / dl.mean())
        self.tf = tf.tocsr()

    def score(self, query: str, rows: np.ndarray) -> np.ndarray:
        q = self.vec.transform([query])
        if q.nnz == 0 or len(rows) == 0:
            return np.zeros(len(rows))
        cols, qtf = q.indices, q.data
        sub = self.tf[rows][:, cols].toarray()
        s = sub * (K1 + 1) / (sub + self.norm[rows, None])
        return (s * (self.idf[cols] * qtf)[None, :]).sum(axis=1)


def load_expansions(path: Path) -> dict[str, str]:
    """query_id → 확장어를 공백으로 이은 문자열(쉼표 목록)."""

    e = pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)
    return {q: " ".join(w.strip() for w in re.split(r"[,，]", x) if w.strip()) for q, x in zip(e["query_id"], e["expansion"], strict=True)}


def expansion_frame(instance_id: str, text: str, bm25: SparseBM25, rows: np.ndarray, doc_ids: np.ndarray) -> pd.DataFrame | None:
    """범위 안 가맹점(rows = 색인 행 번호)의 확장 점수 상위 DEPTH개: query_id, doc_id, exp(÷ 최댓값), erank."""

    if not text or len(rows) == 0:
        return None
    sc = bm25.score(text, rows)
    if sc.max(initial=0.0) <= 0:
        return None
    top = np.argsort(-sc, kind="stable")[:DEPTH]
    keep = top[sc[top] > 0]
    return pd.DataFrame({"query_id": instance_id, "doc_id": doc_ids[rows[keep]], "exp": sc[keep] / sc.max(),
                         "erank": np.arange(1, len(keep) + 1)})


def add_expansion(stage: pd.DataFrame, exp: pd.DataFrame | None, w: float, name: str, brand_min: float) -> pd.DataFrame:
    """1단계(query_id, doc_id, score)에 w × 확장 점수를 더한다. 1단계에 없던 가게는 사례 최솟값에서 시작.
    브랜드 지점(score ≥ brand_min)은 그대로."""

    s = stage[["query_id", "doc_id", "score"]]
    if exp is None or exp.empty or w == 0:
        return _rerank(s, name)
    out = s.merge(exp[["query_id", "doc_id", "exp"]], on=["query_id", "doc_id"], how="outer")
    out["score"] = out["score"].fillna(out.groupby("query_id")["score"].transform("min")).fillna(0.0)
    plain = out["score"] < brand_min
    out.loc[plain, "score"] = out.loc[plain, "score"] + w * out.loc[plain, "exp"].fillna(0.0)
    return _rerank(out[["query_id", "doc_id", "score"]], name)
