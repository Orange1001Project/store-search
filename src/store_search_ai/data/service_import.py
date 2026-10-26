"""사람이 쓴 서비스셋 쿼리(작성자 완료본 + 팀 작성본의 B)를 하나의 쿼리 표로 합친다(docs/SERVICE_QUERYSET.md 4절).

하는 일
- 같은 문자열(공백 제거·소문자)은 한 쿼리로 합치고, 몇 명이 썼는지(`n_writers`)를 남긴다. 여러 묶음에 나오면 우선순위가 앞선 묶음에 둔다.
- 기존 벤치마크(query_families_v1) 쿼리와 같은 문자열을 표시한다. 기존 train과 같으면 그 쿼리로 학습한 모델이 유리하므로 제외한다.
- 묶음마다 dev/test를 나눈다. 같은 근거(업종·카드·가맹점·시장)의 쿼리는 같은 쪽에 둔다 — dev에서 본 카드·업종이 test에 다시
  나오지 않게(그룹 단위 분할).
- 가정위치를 붙인다: D는 고른 시장, B는 표본 가맹점(브랜드 쿼리는 작성자가 고른 시장), 나머지는 쿼리 문자열로 정한 가맹점의
  좌표(전체 가맹점에서 고르므로 가맹점이 밀집한 곳일수록 자주 뽑힘 — 검색 로그가 없을 때의 사용자 위치 대용, 재현 가능).
"""

from __future__ import annotations

import hashlib
import re

import numpy as np
import pandas as pd

SPACE_RE = re.compile(r"\s+")
REGION_SUFFIXES = ("역", "시장", "동", "읍", "면", "구", "시", "군")

OUTPUT_COLUMNS = [
    "query_id", "query", "bundle", "split", "status", "exclude_reason", "intent", "region_text", "region_text_source",
    "location_id", "latitude", "longitude", "location_source", "basis_id", "writers", "n_writers", "also_in_bundles",
    "old_benchmark_split", "writer_notes",
]


def normalize(text: str) -> str:
    return SPACE_RE.sub("", str(text)).casefold()


def _clean(value) -> str:
    return "" if pd.isna(value) else str(value).strip()


def writer_rows(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """작성자 완료본의 `W?_1부_C_E`·`W?_2부_A_D` 시트에서 질의가 있는 줄만 모은다."""

    frames = []
    for name, sheet in sheets.items():
        if not re.fullmatch(r"W\d+_([12]부_[A-Z]_[A-Z]|추가_[A-Z])", name):
            continue
        frame = sheet.copy()
        frame["질의"] = frame["질의"].map(_clean)
        frames.append(frame[frame["질의"] != ""])
    rows = pd.concat(frames, ignore_index=True)
    return pd.DataFrame({
        "query": rows["질의"], "bundle": rows["묶음"], "intent": rows["의도"].map(_clean),
        "region_text": rows["지역표현"].map(_clean), "location_id": rows["가정위치ID"].map(_clean),
        "basis_id": rows["근거ID"].map(_clean), "writer": rows["작성자"].map(_clean), "note": rows["비고"].map(_clean),
    })


def team_b_rows(team: pd.DataFrame, human_methods: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """팀 작성본에서 사람이 쓴 B와 그 밖의 AI 초안을 나눈다. 작성자 이름 대신 작성방식으로 표시한다."""

    team = team[team["질의"].map(_clean) != ""]
    human = team["작성방식"].isin(human_methods)
    b = team[human & (team["묶음"] == "B")]
    rows = pd.DataFrame({
        "query": b["질의"].map(_clean), "bundle": "B", "intent": b["의도"].map(_clean),
        "region_text": b["지역표현"].map(_clean), "location_id": b["가정위치ID"].map(_clean),
        "basis_id": b["근거ID"].map(_clean), "writer": "team:" + b["작성자"].map(_clean), "note": b["비고"].map(_clean),
    })
    return rows.reset_index(drop=True), team[~human].reset_index(drop=True)


def detect_region_text(query: str, store_name: str, address: str, market_name: str) -> str:
    """B 개별 가맹점 쿼리에서 지역 부분을 찾는다('왜관 발톱닥터 네일' → '왜관').

    상호에 없는 토큰 중, 그대로 또는 끝의 역·시장·동 등을 뗀 형태가 가맹점 주소·시장명에 들어 있으면 지역으로 본다.
    """

    place = f"{address} {market_name}"
    name = normalize(store_name)
    found = []
    for token in query.split():
        if normalize(token) in name:
            continue
        stems = {token} | {token[: -len(s)] for s in REGION_SUFFIXES if token.endswith(s) and len(token) > len(s) + 1}
        if any(len(stem) >= 2 and stem in place for stem in stems):
            found.append(token)
    return " ".join(found)


def merge_duplicates(rows: pd.DataFrame, priority: list[str]) -> pd.DataFrame:
    """같은 문자열(정규화)을 한 쿼리로 합친다. 대표 줄은 우선순위가 앞선 묶음의 첫 줄이다."""

    rank = {b: i for i, b in enumerate(priority)}
    rows = rows.assign(_key=rows["query"].map(normalize), _rank=rows["bundle"].map(rank), _order=range(len(rows)))
    out = []
    for _, group in rows.sort_values(["_rank", "_order"]).groupby("_key", sort=False):
        head = group.iloc[0].to_dict()
        head["writers"] = "|".join(dict.fromkeys(group["writer"]))
        head["n_writers"] = group["writer"].nunique()
        head["also_in_bundles"] = "|".join(sorted(set(group["bundle"]) - {head["bundle"]}))
        head["writer_notes"] = " / ".join(n for n in group["note"] if n)
        out.append(head)
    merged = pd.DataFrame(out).sort_values(["_rank", "_order"]).reset_index(drop=True)
    return merged.drop(columns=["_key", "_rank", "_order", "writer", "note"])


def old_benchmark_splits(families: list[dict], inactive_ids: set[str]) -> dict[str, str]:
    """기존 벤치마크 쿼리 문자열(정규화) → split. 비활성 쿼리는 평가·학습에 안 쓰므로 뺀다."""

    out = {}
    for fam in families:
        for i, q in enumerate(fam["queries"], start=1):
            if f"q_{fam['family']}_{i:02d}" not in inactive_ids:
                out[normalize(q["text"])] = fam["split"]
    return out


def split_groups(queries: pd.DataFrame, dev_share: float, seed: int, fixed: dict[str, str] | None = None) -> pd.Series:
    """묶음마다 근거ID(없으면 쿼리) 그룹 단위로 dev/test를 나눈다.

    `fixed`(그룹 키 → split)에 있는 그룹은 그대로 둔다 — 쿼리를 나중에 더해도 이미 나눈 쿼리의 dev/test가 바뀌지 않게
    (2026-10-21, 추가 C 카드). 나머지 그룹은 seed로 섞은 순서대로, 묶음의 dev 몫(고정 그룹 포함)이 찰 때까지 dev에 넣는다.
    """

    fixed = fixed or {}
    split = pd.Series("test", index=queries.index, dtype=object)
    for bundle, frame in queries.groupby("bundle"):
        group_key = frame["basis_id"].where(frame["basis_id"] != "", "q:" + frame["query"].map(normalize))
        sizes = group_key.value_counts()
        dev = {g for g in sizes.index if fixed.get(f"{bundle}|{g}") == "dev"}
        count = int(sizes[list(dev)].sum()) if dev else 0
        free = sorted(g for g in sizes.index if f"{bundle}|{g}" not in fixed)
        rng = np.random.default_rng([seed, sum(map(ord, bundle))])
        for g in [free[i] for i in rng.permutation(len(free))]:
            if count >= dev_share * len(frame):
                break
            dev.add(g)
            count += int(sizes[g])
        split[frame.index[group_key.isin(dev)]] = "dev"
    return split


def split_fixed_from(previous: pd.DataFrame) -> dict[str, str]:
    """이전 쿼리 표에서 그룹 키 → split(활성 쿼리만)."""

    prev = previous[previous["split"].isin(["dev", "test"])]
    keys = prev["basis_id"].where(prev["basis_id"] != "", "q:" + prev["query"].map(normalize))
    return {f"{b}|{k}": sp for b, k, sp in zip(prev["bundle"], keys, prev["split"], strict=True)}


def auto_location(query: str, points: pd.DataFrame) -> pd.Series:
    """지역이 없는 쿼리의 가정위치: 쿼리 문자열의 해시로 가맹점 하나를 골라 그 좌표를 쓴다.

    `points`는 좌표가 있는 전체 가맹점(doc_id, latitude, longitude). 가맹점마다 같은 확률이라 상권이 클수록 자주 뽑힌다 —
    "사용자는 가게가 많은 곳에 많다"는 대용 가정(2026-10-20; 이전에는 표본 시장 151곳을 같은 확률로 골라 작은 시장이 과대표집됐다).
    쿼리 내용과 무관하게 고른다(정답이 있는 곳을 고르면 평가가 쉬워지는 쪽으로 치우친다). doc_id 순으로 정렬해 쓰므로
    코퍼스 파일의 행 순서와 무관하게 재현된다.
    """

    digest = int(hashlib.sha256(normalize(query).encode("utf-8")).hexdigest(), 16)
    return points.iloc[digest % len(points)]


def assign_locations(queries: pd.DataFrame, stores: pd.DataFrame, markets: pd.DataFrame,
                     points: pd.DataFrame) -> pd.DataFrame:
    """가정위치(location_id·좌표·출처)와 B 개별 가맹점 쿼리의 지역표현을 채운다."""

    stores = stores.set_index("표본ID")
    points = points.sort_values("doc_id").reset_index(drop=True)
    markets_by_id = markets.set_index("시장ID")
    loc_ids, lats, lons, sources, regions, region_sources = [], [], [], [], [], []
    for row in queries.itertuples(index=False):
        region, region_source = row.region_text, ("writer" if row.region_text else "")
        if row.bundle == "B" and row.basis_id in stores.index:
            store = stores.loc[row.basis_id]
            loc_ids.append(row.basis_id)
            lats.append(float(store["위도"]))
            lons.append(float(store["경도"]))
            sources.append("store")
            if not region:
                region = detect_region_text(row.query, store["가맹점명"], store["주소"], store["시장명"])
                region_source = "auto" if region else ""
        else:
            if row.location_id in markets_by_id.index:
                market = markets_by_id.loc[row.location_id]
                loc_ids.append(row.location_id)
                lats.append(float(market["위도"]))
                lons.append(float(market["경도"]))
                sources.append("market")
            else:
                point = auto_location(row.query, points)
                loc_ids.append(f"doc:{point['doc_id']}")
                lats.append(float(point["latitude"]))
                lons.append(float(point["longitude"]))
                sources.append("auto_store")
        regions.append(region)
        region_sources.append(region_source)
    return queries.assign(location_id=loc_ids, latitude=lats, longitude=lons, location_source=sources,
                          region_text=regions, region_text_source=region_sources)


def build_service_queries(
    rows: pd.DataFrame,
    priority: list[str],
    old_splits: dict[str, str],
    exclude: list[dict],
    stores: pd.DataFrame,
    markets: pd.DataFrame,
    points: pd.DataFrame,
    dev_share: float,
    seed: int,
    fixed_split: dict[str, str] | None = None,
    previous: pd.DataFrame | None = None,
) -> pd.DataFrame:
    queries = merge_duplicates(rows, priority)
    queries["old_benchmark_split"] = queries["query"].map(lambda q: old_splits.get(normalize(q), ""))
    in_train = queries["old_benchmark_split"] == "train"
    status = np.where(in_train, "excluded", "active").astype(object)
    reason = np.where(in_train, "기존 벤치마크 train 쿼리와 같음(학습에 쓰인 문자열)", "").astype(object)
    for item in exclude:
        hit = (queries["query"].map(normalize) == normalize(item["query"])).to_numpy()
        status[hit], reason[hit] = "excluded", item["reason"]
    queries = queries.assign(status=status, exclude_reason=reason)
    active = queries["status"] == "active"
    split = pd.Series("", index=queries.index, dtype=object)
    split[active] = split_groups(queries[active], dev_share, seed, fixed_split)
    queries = queries.assign(split=split)
    queries = assign_locations(queries, stores, markets, points)
    queries["query_id"] = assign_query_ids(queries, previous)
    return queries[OUTPUT_COLUMNS]


QUERY_ID_RE = re.compile(r"sq_([A-Z])(\d+)")


def assign_query_ids(queries: pd.DataFrame, previous: pd.DataFrame | None = None) -> list[str]:
    """쿼리 ID. 이전 표에 같은 (정규화 문자열, 묶음)이 있으면 그 ID를 그대로 쓰고, 새 쿼리만 묶음별 최대 번호 다음부터 붙인다.

    판정(qrels)은 query_id에 묶여 있어서 줄 순서로 번호를 다시 매기면 안 된다 — 작성 파일을 더하면 앞 번호가 밀린다
    (2026-10-26 점검 3번). 이전 표가 없으면 묶음별 1번부터.
    """

    known: dict[tuple[str, str], str] = {}
    last: dict[str, int] = {}
    if previous is not None:
        for qid, q, b in zip(previous["query_id"], previous["query"], previous["bundle"], strict=True):
            known[(normalize(q), b)] = qid
            m = QUERY_ID_RE.fullmatch(str(qid))
            if m:
                last[m.group(1)] = max(last.get(m.group(1), 0), int(m.group(2)))
    ids = []
    for q, b in zip(queries["query"], queries["bundle"], strict=True):
        qid = known.get((normalize(q), b))
        if qid is None:
            last[b] = last.get(b, 0) + 1
            qid = f"sq_{b}{last[b]:03d}"
        ids.append(qid)
    return ids


def changes_from_previous(previous: pd.DataFrame, queries: pd.DataFrame) -> list[str]:
    """이전 표의 쿼리가 새 표에서 없어졌거나, 문자열·묶음이 바뀌었거나, 활성 쿼리의 split·가정위치가 바뀐 것.
    판정·사례·dev/test 구분이 그 값에 묶여 있으므로 하나라도 있으면 저장하면 안 된다."""

    new = queries.set_index("query_id")
    out = []
    for row in previous.itertuples(index=False):
        if row.query_id not in new.index:
            out.append(f"{row.query_id} '{row.query}' 없어짐")
            continue
        cur = new.loc[row.query_id]
        if normalize(cur["query"]) != normalize(row.query) or cur["bundle"] != row.bundle:
            out.append(f"{row.query_id} '{row.query}'({row.bundle}) → '{cur['query']}'({cur['bundle']})")
        elif row.status == "active" and cur["status"] == "active":
            if cur["split"] != row.split:
                out.append(f"{row.query_id} split {row.split} → {cur['split']}")
            if (round(float(cur["latitude"]), 6), round(float(cur["longitude"]), 6)) != (
                    round(float(row.latitude), 6), round(float(row.longitude), 6)):
                out.append(f"{row.query_id} 가정위치 바뀜")
    return out
