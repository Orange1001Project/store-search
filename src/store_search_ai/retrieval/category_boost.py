"""업종 가산점(docs/archive/SERVICE_PIPELINE_PLAN.md 11-15) — 업종 쿼리의 순위에 '그 가게 업종이 쿼리 업종과 얼마나 맞나'를 조금 더한다.

쿼리 업종은 학습 없이 정한다: 그 쿼리 후보의 1단계 점수 상위 PRF_K개 가게 대표 업종을 순위 가중(1/log2(순위+1))으로 모은 분포(기타 제외)
— 상위 검색 결과로 쿼리 범주를 정하는 방식(APRF-Net, arXiv 2104.11384). 가게의 비중 = 그 분포에서 가게 대표 업종의 몫(0~1).
순서에만 쓰고 관련 확률(X1)에는 넣지 않는다 — 넣으면 같은 대분류 가게가 모두 올라가 노출 정밀도가 떨어졌다(11-14).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

PRF_K = 10


def category_share(run: pd.DataFrame, categories: pd.Series, empty: str = "ETC", k: int = PRF_K) -> pd.Series:
    """run(query_id 또는 instance_id, doc_id, score)의 행마다 그 가게 업종이 쿼리 업종 분포에서 차지하는 몫. 인덱스는 run과 같다."""

    q = "query_id" if "query_id" in run else "instance_id"
    order = run.sort_values([q, "score"], ascending=[True, False])
    top = order.groupby(q).head(k)
    top = top.assign(cat=top["doc_id"].map(categories).fillna(empty), rank=top.groupby(q).cumcount() + 1)
    top = top.assign(w=1 / np.log2(top["rank"] + 1))
    top = top[top["cat"] != empty]
    dist = top.groupby([q, "cat"])["w"].sum()
    dist = dist / dist.groupby(level=0).transform("sum")
    key = pd.MultiIndex.from_arrays([run[q], run["doc_id"].map(categories).fillna(empty)])
    return pd.Series(dist.reindex(key).fillna(0.0).to_numpy(), index=run.index)


def apply_category_boost(run: pd.DataFrame, categories: pd.Series, category_queries: set, gamma: float) -> pd.DataFrame:
    """업종 쿼리(category_queries)의 점수에 γ × 업종 비중을 더한 run(순위는 다시 매기지 않음 — 호출하는 쪽이 정렬)."""

    q = "query_id" if "query_id" in run else "instance_id"
    add = category_share(run, categories).to_numpy() * run[q].isin(category_queries).to_numpy()
    return run.assign(score=run["score"] + gamma * add)


__all__ = ["PRF_K", "apply_category_boost", "category_share"]
