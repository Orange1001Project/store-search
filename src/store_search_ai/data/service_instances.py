"""서비스셋 평가 사례(쿼리 × 가정위치). 같은 쿼리를 두 맥락으로 평가한다.

- random(기본): 쿼리 가져오기 때 정한 가정위치(가맹점 밀도 비례 대용). "근처에 맞는 가게가 없을 때"도 그대로 남는다.
- anchor: 기본 위치 1km 안에 정답이 없는 쿼리에, **의도에 맞는 가게(앵커) 근처**의 위치를 하나 더 붙인다.
  장소 검색 평가의 목표 장소 기준 위치(target-anchored) 방식이다. 이 맥락의 점수는 "근처에 맞는 가게가 있을 때 잘 찾는가"라는
  조건부 점수이고, 정답이 있는 비율 같은 서비스 통계로는 쓰지 않는다.

앵커 고르기(쿼리 내용으로 고르되 시스템 결과는 보지 않는다)
- B 브랜드: 상호(공백 제거·소문자)에 브랜드명이나 별칭이 들어간 가맹점
- A·C: 쿼리·의도 단어(조사 뗌) 중 취급품목에 5번 이상 나오는 말 가운데 **가장 드물게 나오는 단어**(가장 구체적인 업종·품목어)가
  취급품목에 들어간 가맹점. 5번 미만인 말('필요한', '고장')은 업종을 가리키지 않는다고 본다. 상호는 보지 않는다 — 상호의 우연한 글자('양수리점'의 '수리',
  '바지락'의 '바지')가 앵커를 엉뚱한 가게로 끌고 가기 때문이다(2026-10-21 표본 확인 후 수정).
- 자동 선택이 엉뚱한 업종을 고른 쿼리는 진행자가 앵커 단어를 지정한다(설정 `judging.anchor_keywords`, `anchor_rule=keyword`).
- 후보 중 하나를 쿼리 문자열 해시로 고른다(후보마다 같은 확률). 사용자 위치는 앵커 1km 안 가맹점 하나의 좌표(같은 방식으로 고름)라
  앵커는 항상 1km 안에 있지만 사용자가 그 가게 위에 서 있지는 않다.
앵커 가게 자신은 판정 pool에 넣는다(`anchor` 출처). 판정 결과 앵커도 정답이 아니면 그 사례는 정답 없는 사례로 남는다.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

from store_search_ai.data.service_pool import KEYWORD_STOPWORDS, haversine_km

SPACE_RE = re.compile(r"\s+")
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _norm(text) -> str:
    return SPACE_RE.sub("", str(text or "")).casefold()


def _pick(seed_text: str, n: int, salt: str) -> int:
    return int(hashlib.sha256(f"{salt}:{_norm(seed_text)}".encode()).hexdigest(), 16) % n


JOSA = ("으로", "에서", "을", "를", "이", "가", "은", "는", "와", "과", "에", "의", "로", "도")
MIN_ITEM_DF = 5   # 취급품목에 이보다 적게 나오는 말('필요한', '고장')은 업종을 가리키는 말이 아니라고 본다


def strip_josa(token: str) -> str:
    for j in JOSA:
        if token.endswith(j) and len(token) - len(j) >= 2:
            return token[: -len(j)]
    return token


def intent_words(text: str) -> list[str]:
    words = (strip_josa(t) for t in TOKEN_RE.findall(str(text or "")))
    return [w for w in words if len(w) >= 2 and w not in KEYWORD_STOPWORDS]


def answerable_counts(instances: pd.DataFrame, qrels: pd.DataFrame, corpus: pd.DataFrame, radius_km: float) -> pd.Series:
    """사례마다 반경 안 정답(2점 이상) 가맹점 수. 판정은 쿼리 단위라 같은 쿼리의 사례끼리 qrels를 같이 쓴다."""

    pos = qrels[qrels["relevance"] >= 2].merge(corpus[["doc_id", "latitude", "longitude"]], on="doc_id")
    by_query = {q: g for q, g in pos.groupby("query_id")}
    out = {}
    for row in instances.itertuples(index=False):
        g = by_query.get(row.query_id)
        if g is None:
            out[row.instance_id] = 0
            continue
        d = haversine_km(row.latitude, row.longitude, g["latitude"].to_numpy(float), g["longitude"].to_numpy(float))
        out[row.instance_id] = int((d <= radius_km).sum())
    return pd.Series(out)


def anchor_candidates(row, corpus: pd.DataFrame, aliases: dict[str, list[str]], df_cache: dict[str, int] | None = None,
                      keyword: str | None = None) -> np.ndarray:
    names = corpus["_name_norm"].to_numpy()
    if row.bundle == "B":
        q = _norm(row.query)
        variants = {q}
        for canon, vs in aliases.items():
            group = {_norm(v) for v in [canon, *vs]}
            if q in group:
                variants |= group
        return np.flatnonzero([any(v in n for v in variants) for n in names])
    items = corpus["_item_norm"]
    if keyword:   # 진행자가 지정한 앵커 단어
        return np.flatnonzero(items.str.contains(_norm(keyword), regex=False).to_numpy())
    cache = {} if df_cache is None else df_cache
    found = []
    for w in dict.fromkeys(x.casefold() for x in intent_words(row.query) + intent_words(row.intent)):
        if w not in cache:
            cache[w] = int(items.str.contains(w, regex=False).sum())
        if cache[w] >= MIN_ITEM_DF:
            found.append(w)
    if not found:
        return np.array([], dtype=int)
    word = min(found, key=lambda w: (cache[w], w))
    return np.flatnonzero(items.str.contains(word, regex=False).to_numpy())


def build_instances(
    queries: pd.DataFrame,
    qrels: pd.DataFrame,
    corpus: pd.DataFrame,
    aliases: dict[str, list[str]],
    radius_km: float = 1.0,
    anchor_bundles: tuple[str, ...] = ("A", "B", "C"),
    anchor_keywords: dict[str, str] | None = None,
) -> pd.DataFrame:
    """random 사례(모든 활성 쿼리) + anchor 사례(기본 위치 1km 안 정답이 없는 A·C·B 브랜드 쿼리)."""

    corpus = corpus.sort_values("doc_id").reset_index(drop=True).assign(
        _name_norm=lambda d: d["store_name"].map(_norm),
        _item_norm=lambda d: d["item_text"].map(_norm),
    )
    df_cache: dict[str, int] = {}
    base = queries.assign(instance_id=queries["query_id"], context="random", anchor_doc_id="")
    counts = answerable_counts(base, qrels, corpus, radius_km)
    lats, lons = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float)
    rows = []
    for row in base.itertuples(index=False):
        if row.bundle not in anchor_bundles or counts[row.instance_id] > 0:
            continue
        if row.bundle == "B" and row.location_source == "store":
            continue   # 개별 가맹점 쿼리는 이미 그 가게 위치에서 찾는다
        keyword = (anchor_keywords or {}).get(row.query)
        cand = anchor_candidates(row, corpus, aliases, df_cache, keyword)
        if len(cand) == 0:
            continue
        anchor = cand[_pick(row.query, len(cand), "anchor")]
        near = np.flatnonzero(haversine_km(lats[anchor], lons[anchor], lats, lons) <= radius_km)
        spot = near[_pick(row.query, len(near), "spot")]
        rows.append({**row._asdict(), "instance_id": f"{row.query_id}@a", "context": "anchor",
                     "anchor_doc_id": corpus.at[anchor, "doc_id"], "anchor_rule": "keyword" if keyword else "auto", "location_id": f"doc:{corpus.at[spot, 'doc_id']}",
                     "latitude": lats[spot], "longitude": lons[spot], "location_source": "anchor_near"})
    return pd.concat([base, pd.DataFrame(rows)], ignore_index=True)
