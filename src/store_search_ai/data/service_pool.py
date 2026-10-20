"""서비스셋 판정 pool — 쿼리 가정위치에서 반경 안 가맹점만 후보로 시스템 run을 만들고 합친다
(docs/SERVICE_ANNOTATION_GUIDELINE.md 4절).

전국 상위 k개를 판정하면 대부분 반경 밖이라 서비스(현재 위치 1km) 평가에 쓸 수 없다. 반경 안 후보는 쿼리당 수백 곳이라
시스템 상위 k개 + 키워드 후보로 대부분의 정답을 판정할 수 있다.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

EARTH_RADIUS_KM = 6371.0
RUN_COLUMNS = ["query_id", "doc_id", "rank", "score", "system"]
# 키워드 후보에서 무시할 말(어디서나 나오는 서술어·장소어)
KEYWORD_STOPWORDS = {
    "곳", "데", "집", "점", "가게", "매장", "파는", "사는", "살", "먹을", "먹으러", "갈", "가는", "하는", "할", "받는", "있는",
    "수", "좋은", "근처", "동네", "전문점", "샵",
}
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def haversine_km(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    a = np.radians(lat)
    b = np.radians(lon)
    la = np.radians(lats)
    lo = np.radians(lons)
    h = np.sin((la - a) / 2) ** 2 + np.cos(a) * np.cos(la) * np.sin((lo - b) / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h))


def candidates_within(queries: pd.DataFrame, corpus: pd.DataFrame, radius_km: float) -> dict[str, np.ndarray]:
    """query_id → 반경 안 가맹점의 corpus 행 번호(위치가 같은 쿼리는 한 번만 계산)."""

    lats = corpus["latitude"].to_numpy(dtype=float)
    lons = corpus["longitude"].to_numpy(dtype=float)
    by_location: dict[tuple[float, float], np.ndarray] = {}
    out = {}
    for qid, lat, lon in zip(queries["query_id"], queries["latitude"], queries["longitude"], strict=True):
        key = (float(lat), float(lon))
        if key not in by_location:
            by_location[key] = np.flatnonzero(haversine_km(key[0], key[1], lats, lons) <= radius_km)
        out[qid] = by_location[key]
    return out


def distances_km(queries: pd.DataFrame, corpus: pd.DataFrame, cands: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    lats = corpus["latitude"].to_numpy(dtype=float)
    lons = corpus["longitude"].to_numpy(dtype=float)
    return {
        qid: haversine_km(float(lat), float(lon), lats[cands[qid]], lons[cands[qid]])
        for qid, lat, lon in zip(queries["query_id"], queries["latitude"], queries["longitude"], strict=True)
    }


def top_k_run(qid: str, cand_idx: np.ndarray, scores: np.ndarray, doc_ids: np.ndarray, depth: int, system: str) -> pd.DataFrame:
    """반경 안 후보의 점수에서 상위 depth개. 동점은 corpus 순서로(재현 가능)."""

    if len(cand_idx) == 0:
        return pd.DataFrame(columns=RUN_COLUMNS)
    order = np.lexsort((cand_idx, -scores))[:depth]
    return pd.DataFrame({
        "query_id": qid, "doc_id": doc_ids[cand_idx[order]], "rank": np.arange(1, len(order) + 1),
        "score": scores[order], "system": system,
    })


def query_keywords(query: str) -> list[str]:
    """키워드 후보용 단어: 2글자 이상, 서술어·장소어 제외. 띄어쓰기 없이 붙은 '파는곳' 같은 꼬리는 남겨도 매칭에 거의 안 걸린다."""

    return [t for t in TOKEN_RE.findall(query) if len(t) >= 2 and t not in KEYWORD_STOPWORDS]


def lexical_query(query: str, region_text: str = "") -> str:
    """pool용 BM25 쿼리: 서술어·장소어('파는', '곳')와 지역 표현을 뺀 단어. 후보는 이미 반경 안이라 지역 단어는
    지점명이 같은 아무 가게나 끌어온다('뚝섬 식당' → '○○ 뚝섬유원지역점'). 남는 단어가 없으면 원래 쿼리."""

    region = set(TOKEN_RE.findall(region_text or ""))
    words = [w for w in query_keywords(query) if w not in region]
    return " ".join(words) or query


def keyword_run(qid: str, query: str, cand_idx: np.ndarray, texts: np.ndarray, doc_ids: np.ndarray, depth: int) -> pd.DataFrame:
    """쿼리 단어가 상호·취급품목에 들어간 반경 안 가맹점(겹친 단어 수 → 겹친 글자 수 순). 시스템이 놓친 이름 겹침(E 함정)과
    문자 그대로의 정답을 pool에 넣는다."""

    words = query_keywords(query)
    if not words or len(cand_idx) == 0:
        return pd.DataFrame(columns=RUN_COLUMNS)
    cand_texts = texts[cand_idx]
    hits = np.array([sum(w in t for w in words) for t in cand_texts])
    chars = np.array([sum(len(w) for w in words if w in t) for t in cand_texts])
    keep = hits > 0
    scores = (hits * 100 + chars).astype(float)
    return top_k_run(qid, cand_idx[keep], scores[keep], doc_ids, depth, "keyword")


def pool_pairs(runs: pd.DataFrame, depth: int) -> pd.DataFrame:
    """시스템 run 상위 depth개를 (쿼리, 가맹점)으로 합친다. 어느 시스템이 가져왔는지는 `pool_sources`에만 둔다(판정 시트에는 안 보임)."""

    top = runs[runs["rank"] <= depth]
    return (
        top.groupby(["query_id", "doc_id"])["system"]
        .apply(lambda s: "|".join(sorted(set(s))))
        .rename("pool_sources")
        .reset_index()
    )


def judgment_id(query_id: str, doc_id: str) -> str:
    return hashlib.sha1(f"service:{query_id}:{doc_id}".encode()).hexdigest()[:20]


def double_annotation_queries(query_ids: list[str], share: float, seed: int) -> set[str]:
    rng = np.random.default_rng(seed)
    n = round(len(query_ids) * share)
    return set(rng.choice(sorted(query_ids), size=n, replace=False))


SHEET_COLUMNS = ["judgment_id", "query_id", "query", "bundle", "intent_hint", "doc_id", "store_name", "item_text",
                 "market_name", "relevance", "uncertain", "annotator_note"]


def annotation_sheet(pairs: pd.DataFrame, queries: pd.DataFrame, corpus: pd.DataFrame, seed: int) -> pd.DataFrame:
    """판정 시트. 시스템·순위·거리는 넣지 않고, 행 순서를 섞는다(판정자가 출처를 모르게)."""

    q = queries.set_index("query_id")
    c = corpus.set_index("doc_id")
    sheet = pairs.assign(
        judgment_id=[judgment_id(a, b) for a, b in zip(pairs["query_id"], pairs["doc_id"], strict=True)],
        query=pairs["query_id"].map(q["query"]), bundle=pairs["query_id"].map(q["bundle"]),
        intent_hint=pairs["query_id"].map(q["intent"]),
        store_name=pairs["doc_id"].map(c["store_name"]), item_text=pairs["doc_id"].map(c["item_text"]).fillna(""),
        market_name=pairs["doc_id"].map(c["market_name"]), relevance="", uncertain="", annotator_note="",
    )
    return sheet.sample(frac=1, random_state=seed).reset_index(drop=True)[SHEET_COLUMNS]


def runs_outside_radius(runs: pd.DataFrame, queries: pd.DataFrame, corpus: pd.DataFrame, radius_km: float) -> dict[str, int]:
    """시스템별로, 지금 쿼리 가정위치에서 반경 밖이거나 지금 쿼리에 없는 run 행 수. 0이 아니면 쿼리 위치가 바뀐 뒤의
    옛 run이다(예: Colab run을 다시 만들지 않음) — 그대로 pool을 만들면 반경 밖 가게를 판정하게 된다."""

    q = queries.set_index("query_id")[["latitude", "longitude"]]
    c = corpus.set_index("doc_id")[["latitude", "longitude"]]
    known = runs["query_id"].isin(q.index) & runs["doc_id"].isin(c.index)
    out = {}
    for system, frame in runs.groupby("system"):
        ok = known.loc[frame.index]
        f = frame[ok]
        qa, da = q.loc[f["query_id"]].to_numpy(dtype=float), c.loc[f["doc_id"]].to_numpy(dtype=float)
        a, b = np.radians(qa), np.radians(da)
        h = np.sin((b[:, 0] - a[:, 0]) / 2) ** 2 + np.cos(a[:, 0]) * np.cos(b[:, 0]) * np.sin((b[:, 1] - a[:, 1]) / 2) ** 2
        dist = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(h))
        out[system] = int((~ok).sum() + (dist > radius_km + 1e-6).sum())
    return out
