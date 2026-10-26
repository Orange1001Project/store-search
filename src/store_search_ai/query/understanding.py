"""쿼리 이해(query understanding) — 지역 검색의 표준 구조처럼 쿼리를 지역 / 상호·브랜드 / 나머지(업종·상황)로 나눈다.

- 지역: 코퍼스 주소·시장명으로 만든 지명 사전(gazetteer). 시도·시군구·읍면·동·도로명·시장명과 그 줄임말("성남시"→"성남",
  "불광동"→"불광", "구리전통시장"→"구리"). 줄임말은 상품어와 겹치면 쓰지 않는다("우산"은 우산동이 아니라 상품).
  같은 이름이 여러 곳이면(고성군 2곳, 중앙동 수십 곳) 시군구별로 나눠 사용자 위치에서 가장 가까운 곳을 고른다(지도 검색의 근접 우선).
  결과는 그 지역 가게 집합과 중심 좌표.
- 상호·브랜드: 지역을 뺀 나머지가 가게 이름과 서로 포함되면(3글자 이상) 상호 쿼리로 본다. 업종어가 들어 있거나("곱창 구이")
  같은 말이 취급품목에 더 흔하면("치킨") 업종 쿼리로 둔다. 체인(지점 3곳 이상인 이름)은 brand.
- 나머지: 업종·상황 표현. 의미 검색(임베딩)이 맡는다.

규칙 기반이라 결과를 그대로 검사할 수 있다. 업종 분류(가게·쿼리)는 별도 단계에서 붙인다.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from store_search_ai.retrieval.fusion import normalize_name

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
NEAR_KM = 30.0   # 같은 지명이 여러 곳일 때 이 거리 안에 있으면 사용자 근처를 고른다(생활권)
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


@dataclass
class Region:
    tokens: list[str]
    label: str
    doc_idx: np.ndarray
    center: tuple[float, float]


@dataclass
class ParsedQuery:
    query: str
    region: Region | None
    core: str                         # 지역을 뺀 나머지(상호 또는 업종·상황)
    intent: str                       # name | brand | category
    name_doc_idx: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))

    @property
    def region_text(self) -> str:
        return " ".join(self.region.tokens) if self.region else ""


class QueryUnderstanding:
    """코퍼스에서 지명·상호 사전을 만들고 쿼리를 나눈다. corpus 열: store_name, item_text, address, market_name,
    source_region, legal_dong_code, latitude, longitude(순서 = doc_idx)."""

    def __init__(self, corpus: pd.DataFrame, item_min_count: int = 20, brand_min_stores: int = 3):
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

    def _place(self, token: str) -> np.ndarray | None:
        t = token.casefold()
        if t in GENERIC or t in self.item_words:
            return None
        stripped = _strip_any(t, QUERY_SUFFIXES)
        for cand in dict.fromkeys([t, stripped]):
            if len(cand) < 2 or cand not in self.places:
                continue
            explicit = cand != t or (len(t) >= 3 and t.endswith(PLACE_ENDINGS))   # '우산동', '쌍문역'('아동'은 아님)
            if cand in self.admin_keys or explicit or not self.is_category_word(t):
                return self.places[cand]
        if t.endswith(("시장", "상가")) and len(t) >= 4:            # '부평시장' ⊂ '부평깡통시장(구 부산부평시장)'
            hit = self.corpus.index[self.corpus["market_name"].str.replace(" ", "").str.contains(t, regex=False)]
            return hit.to_numpy() if len(hit) else None
        return None

    def parse(self, query: str, user_lat: float | None = None, user_lon: float | None = None) -> ParsedQuery:
        tokens = query.split()
        found = {i: v for i, t in enumerate(tokens) if (v := self._place(t)) is not None}
        # 지역은 쿼리 앞이나 뒤에 붙는다 — 가운데 토큰만 지명이면 상호의 일부일 가능성이 커서 앞·뒤에서 이어진 것만 쓴다
        region_pos = self._run(found, range(len(tokens))) or self._run(found, reversed(range(len(tokens))))
        if len(region_pos) == len(tokens):                          # 전부 지명이면 마지막 토큰은 대상으로 남긴다
            region_pos = sorted(region_pos)[:-1]
        region_pos = sorted(region_pos)
        rest = [t for i, t in enumerate(tokens) if i not in set(region_pos)]
        # '우산 파는 곳' — 남는 게 서술·장소어뿐이면 그 토큰이 찾는 대상. '강남 맛집'·'망원 근처'는 지역을 남긴다
        if rest and all(t in GENERIC - REGION_MODIFIERS for t in rest):
            region_pos = []
        # '남양 수산', '영암 한우', '현대 이발' — 띄어 쓴 상호의 앞부분이 지명과 같은 경우. 붙여 쓴 쿼리가 상호에 있고, 지명 토큰에
        # 지명 끝말(동·역·시장…)이 없고, 남는 말이 상호가 아니면 지역으로 떼지 않는다(상호 일치를 먼저 보는 지도 검색 관례)
        if region_pos and not any(tokens[i].endswith(PLACE_ENDINGS) for i in region_pos):
            whole = normalize_name(query)
            core_try = " ".join(t for i, t in enumerate(tokens) if i not in set(region_pos))
            if len(whole) >= 3 and self._names_s.str.contains(whole, regex=False).any() \
                    and self._intent(core_try)[0] == "category":
                region_pos = []
        region = (self._resolve([tokens[i] for i in region_pos], [found[i] for i in region_pos], user_lat, user_lon)
                  if region_pos else None)
        core = " ".join(t for i, t in enumerate(tokens) if i not in set(region_pos))
        intent, name_idx = self._intent(core)
        return ParsedQuery(query, region, core, intent, name_idx)

    @staticmethod
    def _run(found: dict[int, np.ndarray], order) -> list[int]:
        """앞(또는 뒤)에서 이어지는 지명 토큰. 둘째 토큰부터는 앞 토큰과 같은 곳의 가게가 있어야 붙인다
        ('안산 고잔'은 붙고 '대전 아카데미'의 '아카데미'는 대전에 없는 시장명이라 상호로 남긴다)."""

        pos: list[int] = []
        docs = None
        for i in order:
            if i not in found:
                break
            both = found[i] if docs is None else np.intersect1d(docs, found[i])
            if not len(both):
                break
            pos.append(i)
            docs = both
        return pos

    def _resolve(self, tokens: list[str], sets: list[np.ndarray], user_lat, user_lon) -> Region:
        docs = sets[0]
        for s in sets[1:]:
            docs = np.intersect1d(docs, s)                          # _run에서 겹치는 것만 붙였으므로 비지 않음
        # 시도 이름('대전', '부산')이면 시도 하나로 본다 — 광역시는 구마다 코드 앞 4자리가 달라 쪼개지면 안 됨
        unit = self.sido if any(t.casefold() in SIDO_NAMES for t in tokens) else self.sigungu
        groups = list(pd.Series(docs).groupby(unit[docs]).apply(lambda s: s.to_numpy()))
        if len(groups) > 1:
            # 지도 검색처럼: 사용자 근처(NEAR_KM 안)에 같은 이름이 있으면 가까운 곳, 없으면 가게가 가장 많은(큰) 곳
            near = []
            if user_lat is not None and user_lon is not None:
                def dist(ix):
                    return float(np.hypot(np.median(self.lat[ix]) - user_lat, (np.median(self.lon[ix]) - user_lon) * 0.8)) * 111
                near = [g for g in groups if dist(g) <= NEAR_KM]
            docs = min(near, key=dist) if near else max(groups, key=len)
        return Region(tokens, " ".join(tokens), docs, (float(np.median(self.lat[docs])), float(np.median(self.lon[docs]))))

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
