"""여러 검색 결과(run)를 하나로 합치는 결합 함수 — 하이브리드 검색(docs/SERVICE_PIPELINE_PLAN.md 1-1).

- RRF(Cormack et al. 2009): 점수 = Σ 1/(k + 순위). 점수 크기가 달라도 쓸 수 있고 조정할 값이 k 하나뿐이다.
- 가중합(convex combination, Bruch et al. 2023): 시스템마다 점수를 사례 안에서 정규화(min-max)한 뒤 가중 평균.
  잘 고른 가중치에서는 RRF보다 낫다고 보고됐다. 한 시스템 목록에 없는 문서는 그 시스템 점수를 0(정규화 최솟값)으로 둔다.

run 열: query_id(사례 ID), doc_id, rank, score, system.
"""

from __future__ import annotations

import re

import pandas as pd

RUN_COLUMNS = ["query_id", "doc_id", "rank", "score", "system"]


def _rerank(scores: pd.DataFrame, name: str) -> pd.DataFrame:
    """(query_id, doc_id, score) → 점수 내림차순 순위. 동점은 doc_id 순(재현 가능)."""

    out = scores.sort_values(["query_id", "score", "doc_id"], ascending=[True, False, True])
    out = out.assign(rank=out.groupby("query_id").cumcount() + 1, system=name)
    return out[RUN_COLUMNS].reset_index(drop=True)


def rrf(runs: list[pd.DataFrame], k: float = 60.0, name: str = "rrf") -> pd.DataFrame:
    parts = [r[["query_id", "doc_id"]].assign(score=1.0 / (k + r["rank"])) for r in runs]
    fused = pd.concat(parts).groupby(["query_id", "doc_id"], as_index=False)["score"].sum()
    return _rerank(fused, name)


def minmax(run: pd.DataFrame) -> pd.DataFrame:
    g = run.groupby("query_id")["score"]
    lo, hi = g.transform("min"), g.transform("max")
    span = (hi - lo).where(hi > lo, 1.0)
    return run.assign(score=(run["score"] - lo) / span)


def convex(runs: list[pd.DataFrame], weights: list[float], name: str = "convex") -> pd.DataFrame:
    if len(runs) != len(weights):
        raise ValueError("runs와 weights 길이가 다릅니다")
    parts = [minmax(r)[["query_id", "doc_id", "score"]].assign(score=lambda d, w=w: d["score"] * w)
             for r, w in zip(runs, weights, strict=True)]
    fused = pd.concat(parts).groupby(["query_id", "doc_id"], as_index=False)["score"].sum()
    return _rerank(fused, name)


NAME_STRIP_RE = re.compile(r"\(.*?\)|㈜|\(주\)|주식회사|\s+")


def normalize_name(text: str) -> str:
    return NAME_STRIP_RE.sub("", str(text or "")).casefold()


def name_match(query_core: str, store_name: str, min_len: int = 3) -> bool:
    """상호 일치 신호: 지역 표현을 뺀 쿼리(정규화)가 상호에 들어 있거나 상호가 쿼리에 들어 있다(둘 다 3글자 이상).
    지역 검색에서 가장 강한 신호가 상호 일치다 — 상호명 쿼리("크린토피아", "통영 짱이상회")에서 주로 켜지고,
    업종 쿼리에서는 상호에 업종명이 든 가게("태권도장" → ○○태권도장)에서만 켜진다."""

    q, n = normalize_name(query_core), normalize_name(store_name)
    return len(q) >= min_len and (q in n or (len(n) >= min_len and n in q))


def boost(run: pd.DataFrame, hits: pd.Series, beta: float, name: str) -> pd.DataFrame:
    """정규화 점수에 상호 일치 가산점 beta를 더해 다시 순위를 매긴다. hits는 run 행과 같은 순서의 bool."""

    scored = minmax(run)[["query_id", "doc_id", "score"]]
    scored = scored.assign(score=scored["score"] + beta * hits.to_numpy(dtype=float))
    return _rerank(scored, name)
