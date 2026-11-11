"""쿼리 이해(query understanding) — 지역 검색의 표준 구조처럼 쿼리를 지역 / 상호·브랜드 / 나머지(업종·상황)로 나눈다.

- 지역: 코퍼스 주소·시장명으로 만든 지명 사전 + 공공데이터 지명 사전(data/gazetteer.py — 가맹점이 없는 명동·역·시장도). 시도·시군구·
  읍면·동·도로명·시장명·역과 그 줄임말("성남시"→"성남", "불광동"→"불광", "구리전통시장"→"구리"). 줄임말은 상품어와 겹치면 쓰지 않는다
  ("우산"은 우산동이 아니라 상품). 같은 이름이 여러 곳이면(고성군 2곳, 중앙동 수십 곳) 시군구별 후보 중 검색 중심 30km 안이고 가맹점이
  있는 가장 가까운 곳(지도 검색의 근접 우선), 없으면 공공데이터 근거가 많은 곳(인지도 대리값)을 고르고 나머지는 선택지로 둔다.
  결과(Region)는 검색 범위 — 넓은 지역(시도·시군구·읍면)은 법정동 코드 앞자리, 좁은 지역(동·역·시장)은 중심에서 반경.
- 상호·브랜드: 지역을 뺀 나머지가 가게 이름과 서로 포함되면(3글자 이상) 상호 쿼리로 본다. 업종어가 들어 있거나("곱창 구이")
  같은 말이 취급품목에 더 흔하면("치킨") 업종 쿼리로 둔다. 체인(지점 3곳 이상인 이름)은 brand.
- 나머지: 업종·상황 표현. 의미 검색(임베딩)이 맡는다.

규칙 기반이라 결과를 그대로 검사할 수 있다. 정책 값(반경 등)은 configs/service/search_policy_v1.yaml과 같아야 한다
(tests/test_search_policy.py). 업종 분류(가게·쿼리)는 공식 업종이 오면 별도 단계에서 붙인다(docs/archive/SERVICE_PIPELINE_PLAN.md 11-3).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.retrieval.fusion import normalize_name

GAZETTEER_PATH = "data/geo/gazetteer_v1.parquet"   # scripts/build_gazetteer.py — 공공데이터 지명 사전

SIDO_SHORT = {
    "서울특별시": ["서울"], "부산광역시": ["부산"], "대구광역시": ["대구"], "인천광역시": ["인천"], "광주광역시": ["광주"],
    "대전광역시": ["대전"], "울산광역시": ["울산"], "세종특별자치시": ["세종"], "경기도": ["경기"], "강원특별자치도": ["강원"],
    "강원도": ["강원"], "충청북도": ["충북"], "충청남도": ["충남"], "전북특별자치도": ["전북"], "전라북도": ["전북"],
    "전라남도": ["전남"], "전남광주통합특별시": ["전남", "광주"], "경상북도": ["경북"], "경상남도": ["경남"],
    "제주특별자치도": ["제주"],
}
SIDO_NAMES = {n.casefold() for k, v in SIDO_SHORT.items() for n in [k, *v]}
MARKET_SUFFIXES = ("골목형상점가", "상점가", "전통시장", "종합시장", "골목시장", "상설시장", "오일시장", "시장", "상가", "상권")
QUERY_SUFFIXES = ("역", "시장", "사거리", "삼거리", "오거리", "동", "읍", "면")   # 쿼리 토큰에서 떼어 보는 끝말("쌍문역"→"쌍문")
# 지명·상호로 보지 않는 일반어(시장 이름 '○○가게', 상품권 이름 '온누리' 등과 겹침)
GENERIC = {"가게", "곳", "데", "집", "파는", "사는", "하는", "먹을", "먹는", "배우는", "동네", "근처", "주변", "맛집", "온누리"}
# 지역을 꾸미는 일반어('강남 맛집', '망원 근처') — 남는 말이 이것뿐이어도 앞 토큰은 지역으로 둔다
REGION_MODIFIERS = {"동네", "근처", "주변", "맛집", "온누리"}
NEAR_KM = 30.0   # 같은 지명이 여러 곳일 때 이 거리 안에 있으면 검색 중심 근처를 고른다(생활권)
NAME_FIRST_KM = 10.0   # 최대 검색 반경(회의 결정). 이 안에 쿼리 전체와 이름이 맞는 가게가 있으면 상호 검색을 먼저
POINT_KM = 1.0   # 좁은 지역(동·역·시장)의 첫 반경 — 검색 중심(지도 위치)과 같은 규칙(1km → 10km)
# 지명 사전(공공데이터) 종류별로 중심 좌표를 믿는 순서. 동 중심을 시군구 중심으로 대신한 것(center_source=sigungu)은 맨 뒤
CENTER_PRIORITY = ("station", "market", "hdong", "dong", "sido", "city", "sigungu", "eupmyeon")
AREA_KINDS = ("sido", "city", "sigungu", "eupmyeon")
MIN_CORPUS_PLACE_DOCS = 5   # 가맹점 주소·시장 이름에서만 나온 지명은 근거 가게가 이만큼은 있어야 지명으로 본다('겨울 패딩'의 겨울 = 주소 1곳)
EVIDENCE_FAMILY = {"sido": "admin", "city": "admin", "sigungu": "admin", "eupmyeon": "admin", "dong": "admin", "hdong": "admin",
                   "station": "station", "market": "market"}
PLACE_ENDINGS = ("동", "가", "리", "로", "길", "시장", "상가", "역", "시", "군", "구", "읍", "면")
ROAD_RE = re.compile(r"^([가-힣A-Za-z]+?\d*(?:대로|로|길))")
DONG_RE = re.compile(r"^([가-힣]+?)(\d+)?(동|가|리)$")
WORD_RE = re.compile(r"[^\s(),·/]+")


def _strip_any(text: str, suffixes: tuple[str, ...]) -> str:
    for s in suffixes:
        if text.endswith(s) and len(text) - len(s) >= 2:
            return text[: -len(s)]
    return text


def place_keys(address: str, market_name: str, source_region: str) -> tuple[set[str], set[str]]:
    """가게 하나가 속한 지명 키(정규화). 시도 → 시군구 → 읍면 → 동 → 도로명 → 시장명 순서로 주소에서 뽑는다.
    (행정구역 키, 생활권 키) — 행정구역(시도·시군구·읍면과 그 줄임말 '성남')은 상품어와 겹쳐도 지명으로 본다('제주').
    생활권(동 '불광', 도로 '칠성로', 시장 '웃장')은 상품어와 겹치면 끝말을 붙였을 때만 지명으로 본다('우산' ≠ 우산동)."""

    admin: set[str] = set()
    local: set[str] = set()
    sido = str(source_region or "")
    if sido:
        admin.add(sido)
        admin.update(SIDO_SHORT.get(sido, []))
    words = WORD_RE.findall(str(address or ""))
    for w in words[1:6]:
        if w[-1] in "시군구" and len(w) >= 2 and not w[0].isdigit():
            admin.add(w)
            if len(w) >= 3:
                admin.add(w[:-1])                                  # 성남시 → 성남 (중구·동구처럼 한 글자는 뺌)
        elif w[-1] in "읍면" and len(w) >= 3:
            admin.update({w, w[:-1]})
        m = DONG_RE.match(w)
        if m and not ROAD_RE.match(w):
            base = m.group(1)
            local.update({w, base + m.group(3)})                   # 고잔1동 → 고잔동, 묵동
            if m.group(3) == "동" and len(base) >= 2:
                local.add(base)                                    # 불광동 → 불광
            if m.group(3) == "가" and m.group(2) and len(base) >= 2:
                local.add(base)                                    # 명동1가 → 명동, 을지로3가 → 을지로
        r = ROAD_RE.match(w)
        if r and len(r.group(1)) >= 3:
            road = r.group(1)
            if road.endswith("길"):
                road = re.sub(r"\d+$", "", re.sub(r"\d+(번)?길$", "", road))
            if len(road) >= 3:
                local.add(road)                                    # 원효로41길 → 원효로
    # 시장명: 전체·괄호 뺀 이름·끝말 뺀 이름, 시장 끝말로 끝나는 단어. 앞에 붙은 도시명('안산 ○○시장'의 '안산')은 키로 쓰지 않는다
    m = str(market_name or "").casefold()
    for name in {m, re.sub(r"\(.*?\)", "", m)}:
        name = name.replace(" ", "")
        if len(name) >= 2:
            local.add(name)
            core = _strip_any(name, MARKET_SUFFIXES)
            if core != name and len(core) >= 2:
                local.add(core)                                    # 구리전통시장 → 구리
    for w in WORD_RE.findall(m):
        if len(w) >= 3 and not w.endswith(MARKET_SUFFIXES):
            local.add(w)                                           # '대사동 보문산 골목형상점가'의 '보문산'
        elif w.endswith(MARKET_SUFFIXES) and len(w) >= 3:
            local.add(w)
            core = _strip_any(w, MARKET_SUFFIXES)
            if core != w and len(core) >= 2:
                local.add(core)
    admin = {k.casefold() for k in admin}
    return admin, {k.casefold() for k in local} - admin


def load_gazetteer(path: str | Path = GAZETTEER_PATH) -> pd.DataFrame | None:
    """지명 사전이 있으면 읽는다(없으면 None — 가맹점 주소로 만든 지명만 쓴다)."""

    return pd.read_parquet(path) if Path(path).exists() else None


@dataclass
class Candidate:
    """같은 지명 키의 후보 한 곳(시군구 하나, 시도 이름이면 시도 하나)."""

    unit: str                         # 법정동 코드 앞 4자리(구가 있는 시는 시 하나) 또는 시도 2자리
    lat: float
    lon: float
    docs: np.ndarray                  # 이 지명 키를 가진 가맹점(코퍼스 주소·시장명에서)
    kinds: frozenset                  # corpus / sido / city / sigungu / eupmyeon / dong / hdong / station / market
    scope: str                        # area(코드 앞자리로 거름) | point(중심에서 반경)
    code_prefix: str                  # area일 때 legal_dong_code 앞자리
    name: str                         # 표시용(지명 사전 이름, 없으면 키)
    center_is_proxy: bool = False     # 중심을 시군구 중심으로 대신함(가게·행정동이 없는 법정동)

    @property
    def sido(self) -> str:
        return self.unit[:2]


@dataclass
class Region:
    tokens: list[str]
    label: str
    doc_idx: np.ndarray               # 이 지역으로 검색할 때의 가맹점(area: 코드 앞자리, point: 키 가게 ∪ 중심 POINT_KM 안)
    center: tuple[float, float]
    scope: str = "point"
    code_prefix: str = ""
    kinds: frozenset = frozenset()
    alternatives: list[tuple[str, float, float]] = field(default_factory=list)   # 같은 이름의 다른 곳(화면 선택지)


@dataclass
class ParsedQuery:
    query: str
    region: Region | None
    core: str                         # 지역을 뺀 나머지(상호 또는 업종·상황)
    intent: str                       # name | brand | category
    name_doc_idx: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    name_key: str = ""                # 상호 일치에 쓸 말. 보통 core, 띄어 쓴 상호('남양 수산')면 쿼리 전체
    # 쿼리 전체가 검색 중심 NAME_FIRST_KM 안 가게 이름에 들어 있음('신촌 설렁탕' → 근처 '신촌설렁탕'). 검색은 지역 필터 대신
    # 검색 중심에서 상호 검색을 먼저 하고, 파싱한 지역은 다른 해석(선택지)으로 둔다.
    name_first: bool = False

    @property
    def region_text(self) -> str:
        return " ".join(self.region.tokens) if self.region else ""


class QueryUnderstanding:
    """코퍼스에서 지명·상호 사전을 만들고 쿼리를 나눈다. corpus 열: store_name, item_text, address, market_name,
    source_region, legal_dong_code, latitude, longitude(순서 = doc_idx).
    gazetteer(data/geo/gazetteer_v1.parquet, data/gazetteer.py)를 주면 가맹점이 없는 곳의 지명(명동, 역, 시장)도 알아본다."""

    def __init__(self, corpus: pd.DataFrame, item_min_count: int = 20, brand_min_stores: int = 3,
                 gazetteer: pd.DataFrame | None = None, min_corpus_place_docs: int = MIN_CORPUS_PLACE_DOCS):
        self.min_corpus_place_docs = min_corpus_place_docs
        self.corpus = corpus.reset_index(drop=True)
        self.lat = self.corpus["latitude"].to_numpy(float)
        self.lon = self.corpus["longitude"].to_numpy(float)
        # 같은 지명이 여러 곳인지 가를 단위: 법정동 코드 앞 4자리(구가 있는 시는 구를 묶어 시 하나 — 성남시 수정·중원·분당구)
        self.sigungu = self.corpus["legal_dong_code"].astype(str).str[:4].to_numpy()
        self.sido = self.corpus["legal_dong_code"].astype(str).str[:2].to_numpy()
        index: dict[str, list[int]] = {}
        self.admin_keys: set[str] = set()
        for i, (a, m, s) in enumerate(zip(self.corpus["address"], self.corpus["market_name"], self.corpus["source_region"],
                                          strict=True)):
            admin, local = place_keys(a, m, s)
            self.admin_keys |= admin
            for k in admin | local:
                index.setdefault(k, []).append(i)                  # 같은 이름은 출처(주소·시장)와 상관없이 합친다
        self.places = {k: np.unique(v) for k, v in index.items()}
        items = self.corpus["item_text"].fillna("").str.strip().str.casefold()
        counts = items[items != ""].value_counts()
        self.item_words = set(counts[counts >= item_min_count].index)   # "한식", "치킨" — 업종어는 지역·상호로 보지 않음
        self._items_s = items
        self._category_cache: dict[str, bool] = {}
        self.names = self.corpus["store_name"].map(normalize_name).to_numpy()
        self._names_s = pd.Series(self.names)
        bases = Counter(self._brand_base(n) for n in self.corpus["store_name"])
        self.brands = {b for b, c in bases.items() if c >= brand_min_stores and len(b) >= 2}
        self.codes = self.corpus["legal_dong_code"].astype(str).to_numpy().astype(str)   # 고정 길이 문자열(np.char용)
        self.gaz: dict[str, pd.DataFrame] = {}
        if gazetteer is not None:
            g = gazetteer.dropna(subset=["lat", "lon"])
            self.gaz = {k: rows for k, rows in g.groupby("key")}
            # 행정구역 이름(시도·시군구·읍면 전체 이름)만 상품어와 겹쳐도 지명으로 본다. 읍면 줄임말('청소면'→'청소')은 생활권 취급
            admin = g["kind"].isin(["sido", "city", "sigungu"]) | ((g["kind"] == "eupmyeon") & g["key"].str.endswith(("읍", "면")))
            self.admin_keys |= set(g.loc[admin, "key"])
            # 약한 키: 동·읍면·시장 이름에서 끝말만 뗀 줄임말('생일면'→'생일', '학교면'→'학교')이고 다른 근거(가맹점 주소, 역, 시군구,
            # 줄이지 않은 이름)가 없는 것. 일반 명사와 겹치기 쉬워 끝말을 붙여 쓴 경우('생일면')에만 지명으로 본다.
            last = g["name"].str.replace(r"\(.*?\)", "", regex=True).str.split().str[-1].str.casefold()
            strong = (g["key"] == last) | g["kind"].isin(["station", "sido", "city", "sigungu"])
            self.weak_keys = set(g["key"]) - set(g.loc[strong, "key"])
        else:
            self.weak_keys = set()
        self._cand_cache: dict[tuple[str, bool], list[Candidate]] = {}

    @staticmethod
    def _brand_base(store_name: str) -> str:
        """지점명을 뗀 이름: 'GS25 여주시청점' → 'gs25'. 띄어쓰기 없는 'GS25여주점'은 그대로(브랜드 판정은 포함 관계로 보완)."""

        words = str(store_name or "").split()
        if len(words) >= 2 and words[-1].endswith("점"):
            words = words[:-1]
        return normalize_name(" ".join(words))

    def is_category_word(self, token: str) -> bool:
        """업종·상품을 뜻하는 단어인가: 일반어이거나 취급품목에 20곳 이상 들어 있다('우산', '곱창', '아동')."""

        t = token.casefold()
        if t not in self._category_cache:
            self._category_cache[t] = (t in GENERIC or t in self.item_words or t.endswith("가게")
                                       or int(self._items_s.str.contains(t, regex=False).sum()) >= 20)
        return self._category_cache[t]

    def _place(self, token: str) -> list[Candidate] | None:
        t = token.casefold()
        if t in GENERIC or t in self.item_words:
            return None
        stripped = _strip_any(t, QUERY_SUFFIXES)
        for cand in dict.fromkeys([t, stripped]):
            if len(cand) < 2 or (cand not in self.places and cand not in self.gaz):
                continue
            explicit = cand != t or (len(t) >= 3 and t.endswith(PLACE_ENDINGS))   # '우산동', '쌍문역'('아동'은 아님)
            if cand in self.weak_keys and cand not in self.places and not explicit:
                continue
            if cand in self.admin_keys or explicit or not self.is_category_word(t):
                return self._candidates(cand, by_sido=cand in SIDO_NAMES)
        if t.endswith(("시장", "상가")) and len(t) >= 4:            # '부평시장' ⊂ '부평깡통시장(구 부산부평시장)'
            hit = self.corpus.index[self.corpus["market_name"].str.replace(" ", "").str.contains(t, regex=False)]
            return self._group(t, hit.to_numpy(), pd.DataFrame(), by_sido=False) if len(hit) else None
        return None

    def _candidates(self, key: str, by_sido: bool) -> list[Candidate]:
        if (key, by_sido) not in self._cand_cache:
            self._cand_cache[(key, by_sido)] = self._group(key, self.places.get(key, np.array([], dtype=int)),
                                                           self.gaz.get(key, pd.DataFrame()), by_sido)
        return self._cand_cache[(key, by_sido)]

    def _group(self, key: str, docs: np.ndarray, gaz: pd.DataFrame, by_sido: bool) -> list[Candidate]:
        """지명 키의 가맹점·지명 사전 행을 시군구(시도 이름이면 시도) 단위로 묶어 후보를 만든다."""

        unit_of = self.sido if by_sido else self.sigungu
        groups: dict[str, dict] = {}
        for u, ix in pd.Series(docs, dtype=int).groupby(unit_of[docs] if len(docs) else []):
            groups[u] = {"docs": ix.to_numpy(), "rows": []}
        for r in gaz.itertuples():
            u = r.sido_code if (by_sido or r.kind == "sido") else str(r.sigungu_code)[:4]
            groups.setdefault(u, {"docs": np.array([], dtype=int), "rows": []})["rows"].append(r)
        out = []
        for u, g in groups.items():
            rows, ix = g["rows"], g["docs"]
            kinds = frozenset({r.kind for r in rows} | ({"corpus"} if len(ix) else set()))
            area_rows = [r for r in rows if r.kind in AREA_KINDS]
            scope = "area" if area_rows or (not rows and key in self.admin_keys) else "point"
            if area_rows:   # 읍면은 같은 이름의 시군이 있으면 뒤로('정선'·'문경' = 정선군·문경시, 포털 지도 검색 관례 — 2026-11-05 P0),
                # 그 밖에는 가장 좁은 행정구역(코드가 긴 것 — '제주' = 제주시)
                ranked = sorted(area_rows, key=lambda r: (r.kind == "eupmyeon", -len(str(r.code_prefix))))
                prefix = str(ranked[0].code_prefix)
            else:
                ranked = sorted(rows, key=lambda r: (r.center_source == "sigungu",
                                                     CENTER_PRIORITY.index(r.kind) if r.kind in CENTER_PRIORITY else 99))
                prefix = u if scope == "area" else ""
            # 중심: 지명 사전 좌표. 단, 좁은 지역인데 시군구 중심으로 대신한 좌표뿐이면 그 지명 가게들의 중앙값이 더 정확하다
            proxy = False
            if ranked and not (scope == "point" and len(ix) and ranked[0].center_source == "sigungu"):
                lat, lon, name = float(ranked[0].lat), float(ranked[0].lon), str(ranked[0].name)
                proxy = scope == "point" and ranked[0].center_source == "sigungu"
                # 넓은 행정동·법정동의 다각형 중심은 산·논일 수 있다('진잠' = 진잠동 중심 1km 안 가게 0곳) — 그 지명 가게들의 중앙값이
                # 중심 1km 안 가게를 더 많이 덮으면 그쪽을 쓴다(역·시장 좌표는 정확해서 그대로). 2026-11-05 P0
                if scope == "point" and ranked[0].kind in ("dong", "hdong") and len(ix) >= self.min_corpus_place_docs:
                    mlat, mlon = float(np.nanmedian(self.lat[ix])), float(np.nanmedian(self.lon[ix]))
                    if self._count_near(mlat, mlon) > 2 * self._count_near(lat, lon):
                        lat, lon = mlat, mlon
            else:
                lat, lon = float(np.nanmedian(self.lat[ix])), float(np.nanmedian(self.lon[ix]))
                name = str(ranked[0].name) if ranked else key
            out.append(Candidate(u, lat, lon, ix, kinds, scope, prefix, name, proxy))
        # 지명 사전에 같은 이름의 행정구역이 있으면, 가맹점 주소에서만 나온 넓은 지역 후보는 버린다 — 주소와 법정동 코드가 어긋난
        # 가게('대전광역시 동구 …'인데 코드는 대덕구 30230) 하나가 별도 후보가 되어 '근처'로 뽑히는 것을 막는다
        if any(c.scope == "area" and c.kinds - {"corpus"} for c in out):
            out = [c for c in out if not (c.scope == "area" and c.kinds == {"corpus"})]
        # 후보가 전부 가맹점 주소·시장 이름에서만 나왔고 근거 가게도 적으면 지명이 아니다('겨울 패딩'의 겨울 = 주소 1곳). 다른 근거가
        # 있는 이름이면 작은 후보도 남긴다 — 버리면 검색 중심 근처의 작은 '현대'를 놓치고 먼 현대시장으로 넘어간다(2026-11-05 P0)
        if out and all(c.kinds == {"corpus"} and len(c.docs) < self.min_corpus_place_docs for c in out):
            return []
        return out

    def _count_near(self, lat: float, lon: float) -> int:
        return int((np.hypot(self.lat - lat, (self.lon - lon) * 0.8) * 111 <= POINT_KM).sum())

    def in_area(self, code_prefix: str) -> np.ndarray:
        """법정동 코드 앞자리(여러 개면 '|')에 드는 가맹점 — 넓은 지역 필터. 옛 광주광역시 = 5개 구 코드."""

        return np.char.startswith(self.codes[:, None], np.array(code_prefix.split("|"))).any(axis=1)

    @staticmethod
    def _contains(outer: Candidate, inner: Candidate) -> bool:
        """outer 안에 inner가 있나. 넓은 지역(시도·시군구)은 코드 단위로, 좁은 지역(동·역·시장)은 같은 시군구 3km 안."""

        if outer.scope == "area":
            return inner.sido == outer.sido if len(outer.unit) == 2 else inner.unit[:4] == outer.unit
        return (len(outer.unit) == len(inner.unit) == 4 and outer.unit == inner.unit
                and float(np.hypot(outer.lat - inner.lat, (outer.lon - inner.lon) * 0.8) * 111) <= 3.0)

    @classmethod
    def _compatible(cls, a: Candidate, b: Candidate) -> bool:
        """두 지명 토큰이 같은 곳을 가리키나('안산 고잔', '서울 중구', '성남 분당') — 어느 쪽이든 다른 쪽 안에 있으면."""

        return cls._contains(a, b) or cls._contains(b, a)

    def parse(self, query: str, center_lat: float | None = None, center_lon: float | None = None) -> ParsedQuery:
        # center = 검색 중심(정책 location.priority로 정한 지도 포커스 — 10-30 회의). GPS 좌표를 따로 넣지 않는다.
        # 같은 지명 여러 곳(NEAR_KM), 상호 우선(NAME_FIRST_KM), 브랜드 거리순, 상호 완전 일치 50km 모두 이 점 기준(PR #9 리뷰 1번)
        tokens = query.split()
        found = {i: v for i, t in enumerate(tokens) if (v := self._place(t))}
        # 지역은 쿼리 앞이나 뒤에 붙는다 — 가운데 토큰만 지명이면 상호의 일부일 가능성이 커서 앞·뒤에서 이어진 것만 쓴다
        region_pos = self._run(found, range(len(tokens))) or self._run(found, reversed(range(len(tokens))))
        if len(region_pos) == len(tokens):                          # 전부 지명이면 마지막 토큰은 대상으로 남긴다
            region_pos = sorted(region_pos)[:-1]
        region_pos = sorted(region_pos)
        rest = [t for i, t in enumerate(tokens) if i not in set(region_pos)]
        # '우산 파는 곳' — 남는 게 서술·장소어뿐이면 그 토큰이 찾는 대상. '강남 맛집'·'망원 근처'는 지역을 남긴다
        if rest and all(t in GENERIC - REGION_MODIFIERS for t in rest):
            region_pos = []
        region = (self._resolve([tokens[i] for i in region_pos], [found[i] for i in region_pos], center_lat, center_lon)
                  if region_pos else None)
        core = " ".join(t for i, t in enumerate(tokens) if i not in set(region_pos))
        intent, name_idx = self._intent(core)
        # '남양 수산', '영암 한우' — 띄어 쓴 상호의 앞부분이 지명과 같은 경우. 지역은 그대로 두고(수원 갈비·강남 치과의 지역을
        # 지우지 않게), 상호 일치는 쿼리 전체로 본다: 지명 끝말(동·역·시장…)이 없고 붙여 쓴 쿼리가 실제 상호에 들어 있을 때.
        # 그 가게가 검색 중심 NAME_FIRST_KM 안에 있으면 상호 검색을 먼저 한다(name_first, 지도 검색의 상호 우선 관례).
        name_key = core
        name_first = False
        if region_pos and not any(tokens[i].endswith(PLACE_ENDINGS) for i in region_pos):
            whole = normalize_name(query)
            if len(whole) >= 3:
                hit = np.flatnonzero(self._names_s.str.contains(whole, regex=False).to_numpy())
                if len(hit):
                    name_key = query
                    if center_lat is not None and center_lon is not None:
                        d = np.hypot(self.lat[hit] - center_lat, (self.lon[hit] - center_lon) * 0.8) * 111
                        name_first = bool((d <= NAME_FIRST_KM).any())
        return ParsedQuery(query, region, core, intent, name_idx, name_key, name_first)

    def _run(self, found: dict[int, list[Candidate]], order) -> list[int]:
        """앞(또는 뒤)에서 이어지는 지명 토큰. 둘째 토큰부터는 앞 토큰 후보 안에 있는(또는 감싸는) 후보가 있어야 붙인다
        (_compatible — '안산 고잔'·'서울 중구'는 붙고, '대전 아카데미'의 '아카데미'는 대전 안에 없는 지명이라 상호로 남긴다)."""

        pos: list[int] = []
        prev: list[Candidate] | None = None
        for i in order:
            if i not in found:
                break
            cands = found[i] if prev is None else [c for c in found[i] if any(self._compatible(c, p) for p in prev)]
            if not cands:
                break
            pos.append(i)
            prev = cands
        return pos

    def _resolve(self, tokens: list[str], cand_lists: list[list[Candidate]], center_lat, center_lon) -> Region:
        # 가장 좁은 토큰(시도 단위가 아닌 것, 여럿이면 뒤쪽)의 후보 중 다른 토큰과 같은 곳인 것
        main = min(range(len(tokens)), key=lambda i: (all(len(c.unit) == 2 for c in cand_lists[i]), -i))
        cands = [c for c in cand_lists[main]
                 if all(any(self._compatible(c, o) for o in cand_lists[j]) for j in range(len(tokens)) if j != main)]
        cands = cands or cand_lists[main]
        has_center = center_lat is not None and center_lon is not None

        def dist(c: Candidate) -> float:
            if c.kinds == frozenset({"dong"}) and c.center_is_proxy:
                return np.inf                                       # 좌표 근거가 없는 법정동(가게·행정동 없음) — 거리를 잴 수 없다
            d = float(np.hypot(c.lat - center_lat, (c.lon - center_lon) * 0.8) * 111)
            if c.scope == "area" and len(c.docs):                   # 검색 중심이 그 지역 안(2km 안에 그 지역 가게)이면 0
                inside = np.hypot(self.lat[c.docs] - center_lat, (self.lon[c.docs] - center_lon) * 0.8) * 111
                d = 0.0 if float(np.nanmin(inside)) <= 2.0 else d
            return d

        def prominence(c: Candidate) -> tuple:
            # 인지도의 대리값(검색 로그·방문 수가 없어서): 시도인가 → 공공데이터 근거가 몇 갈래인가(행정구역 / 역 / 시장 — 같은
            # 갈래는 한 번만) → 가맹점 수. 3km 안 같은 이름 후보는 한 생활권으로 합쳐 센다(서울 신촌 = 서대문 신촌동 + 마포 신촌역).
            # '명동'은 서울 중구(행정구역+역)가 제천 명동(행정구역)보다, '서면'은 부산 서면(역+시장)이 춘천 서면(행정구역)보다 앞선다.
            near = [o for o in cands if float(np.hypot(o.lat - c.lat, (o.lon - c.lon) * 0.8) * 111) <= 3.0]
            kinds = frozenset().union(*(o.kinds for o in near))
            families = {EVIDENCE_FAMILY[k] for k in kinds if k in EVIDENCE_FAMILY}
            return ("sido" in c.kinds, len(families), sum(len(o.docs) for o in near))

        def searchable(c: Candidate) -> bool:
            # 그 지역으로 찾을 가맹점이 있나(지명 가게, 넓은 지역은 코드 안, 좁은 지역은 중심 POINT_KM 안). 가맹점이 없는 같은
            # 이름의 근처 지명(양주 장흥면)은 '근처 우선'으로 고르지 않는다 — 가맹점만 보여 주는 서비스라 결과가 비기 때문
            if len(c.docs):
                return True
            if c.scope == "area":
                return bool(self.in_area(c.code_prefix).any()) if c.code_prefix else False
            return bool((np.hypot(self.lat - c.lat, (self.lon - c.lon) * 0.8) * 111 <= POINT_KM).any())

        chosen = cands[0]
        if len(cands) > 1:
            near = [c for c in cands if dist(c) <= NEAR_KM and searchable(c)] if has_center else []
            chosen = min(near, key=dist) if near else max(cands, key=prominence)
        docs = chosen.docs
        for j, cl in enumerate(cand_lists):                         # '안산 고잔': 두 토큰 모두에 걸린 가게
            if j != main:
                other = [c.docs for c in cl if self._compatible(chosen, c)]
                both = np.intersect1d(docs, np.concatenate(other)) if other else docs
                docs = both if len(both) else docs
        if chosen.scope == "area":                                  # 넓은 지역: 법정동 코드 앞자리 안 가게 전부
            docs = np.union1d(docs, np.flatnonzero(self.in_area(chosen.code_prefix)))
        else:                                                       # 좁은 지역: 지명 가게 ∪ 중심 POINT_KM 안
            d = np.hypot(self.lat - chosen.lat, (self.lon - chosen.lon) * 0.8) * 111
            docs = np.union1d(docs, np.flatnonzero(d <= POINT_KM))
        alts = [(c.name, c.lat, c.lon) for c in sorted(cands, key=prominence, reverse=True) if c is not chosen]
        return Region(tokens, " ".join(tokens), docs.astype(int), (chosen.lat, chosen.lon), chosen.scope,
                      chosen.code_prefix, chosen.kinds, alts)

    def _intent(self, core: str) -> tuple[str, np.ndarray]:
        key = normalize_name(core)
        empty = np.array([], dtype=int)
        if len(key) < 2 or key in self.item_words:
            return "category", empty
        words = core.split()
        brand = key in self.brands and len(words) == 1
        if not brand and any(self.is_category_word(t) for t in words):   # '곱창 구이', '생선 가게', '옷가게' 같은 업종 표현
            return "category", empty
        if len(key) >= 3:
            inside = {key[i:j] for i in range(len(key)) for j in range(i + 3, len(key) + 1)}   # 쿼리 안에 든 상호
            hit = np.flatnonzero(self._names_s.str.contains(key, regex=False).to_numpy() | np.isin(self.names, list(inside)))
        else:
            hit = np.flatnonzero(self.names == key)
        if not len(hit):
            return "category", hit
        n_item = int(self._items_s.str.contains(key, regex=False).sum()) if len(key) <= 6 else 0
        if n_item > len(hit) and not brand:                         # '치킨'·'커피'처럼 업종어로 더 흔함
            return "category", empty
        return ("brand" if brand else "name"), hit
