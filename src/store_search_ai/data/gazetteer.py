"""공공데이터 지명 사전(gazetteer) — 가맹점이 없는 곳의 지명(명동, 역 이름, 가맹점 없는 시장)도 알아보게 한다.

가맹점 주소로 만든 지명 사전(query/understanding.py)은 가맹점이 있는 곳만 안다. "명동 칼국수"에서 '명동'을 모르면
지명이 아니라 검색어로 처리돼 사용자 근처의 엉뚱한 가게가 나온다. 지명을 알아야 "그 근처에 없어요"라고 말할 수 있다.

출처(모두 공공데이터, 원본은 저장소 밖 — scripts/build_gazetteer.py --src)
  - 행정안전부 법정동코드: 시도·시군구·읍면동 이름과 코드. 코퍼스 legal_dong_code와 같은 체계(2026-07 전남광주 통합 반영).
  - 통계청 SGIS 행정동 경계(BND_ADM_DONG_PG, EPSG:5186) + 센서스 지역 코드: 행정동 이름과 중심 좌표, 시군구 중심 좌표.
  - 전체 도시철도역사정보: 역 이름·좌표.
  - 전국전통시장표준데이터: 시장 이름·좌표(가맹점이 없는 시장 포함).

kind와 쓰임(docs/archive/SERVICE_PIPELINE_PLAN.md 11절)
  - 넓은 지역(scope=area): sido, city(구가 있는 시), sigungu, eup·myeon — 코퍼스 legal_dong_code 앞자리(code_prefix)로 거른다.
  - 좁은 지역(scope=point): dong(법정동), hdong(행정동), station, market — 중심 좌표에서 반경(1km → 10km)으로 찾는다.
"""

from __future__ import annotations

import io
import re
import struct
from itertools import pairwise
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.query.understanding import SIDO_SHORT

# EPSG:5186 (Korea 2000 / Central Belt 2010): GRS80, 원점 38N 127E, 축척 1, 가산 (200000, 600000)
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = 2 * _F - _F * _F
_EP2 = _E2 / (1 - _E2)
_LAT0, _LON0, _K0, _FE, _FN = np.radians(38.0), np.radians(127.0), 1.0, 200000.0, 600000.0

MERGED_SIDO = {"광주광역시": "전남광주통합특별시", "전라남도": "전남광주통합특별시"}   # SGIS 2025-06 → 법정동 2026-07
OLD_METRO = {"광주": ("12", ["동구", "서구", "남구", "북구", "광산구"])}               # 통합 시도 안의 옛 광역시(시도코드, 구)
STATION_PAREN = re.compile(r"\((.*?)\)")
MARKET_SUFFIXES = ("골목형상점가", "상점가", "전통시장", "종합시장", "골목시장", "상설시장", "오일시장", "시장", "상가", "상권")


def _meridian(phi):
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    return _A * ((1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
                 + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi) - (35 * e6 / 3072) * np.sin(6 * phi))


def tm_to_wgs84(x, y) -> tuple[np.ndarray, np.ndarray]:
    """EPSG:5186 평면 좌표(m) → 위도·경도(도). 횡메르카토르 역변환(Snyder 1987, 식 8-18~8-25). GRS80 ≈ WGS84(1m 미만 차이)."""

    x, y = np.asarray(x, float), np.asarray(y, float)
    m = _meridian(_LAT0) + (y - _FN) / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - np.sqrt(1 - _E2)) / (1 + np.sqrt(1 - _E2))
    phi1 = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * np.sin(2 * mu) + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * np.sin(4 * mu)
            + (151 * e1 ** 3 / 96) * np.sin(6 * mu) + (1097 * e1 ** 4 / 512) * np.sin(8 * mu))
    s, c, t = np.sin(phi1), np.cos(phi1), np.tan(phi1)
    c1, t1 = _EP2 * c ** 2, t ** 2
    n1 = _A / np.sqrt(1 - _E2 * s ** 2)
    r1 = _A * (1 - _E2) / (1 - _E2 * s ** 2) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = phi1 - (n1 * t / r1) * (d ** 2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * _EP2) * d ** 4 / 24
                                  + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * _EP2 - 3 * c1 ** 2) * d ** 6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d ** 3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * _EP2 + 24 * t1 ** 2) * d ** 5 / 120) / c
    return np.degrees(lat), np.degrees(lon)


def polygon_centroids(shp_path: str | Path) -> list[tuple[float, float, float]]:
    """ESRI shapefile(Polygon) 레코드마다 (면적 m², 중심 x, 중심 y). 여러 고리·구멍은 부호 있는 면적으로 합친다."""

    data = Path(shp_path).read_bytes()
    out = []
    pos = 100
    while pos < len(data):
        _, words = struct.unpack(">ii", data[pos:pos + 8])
        rec = data[pos + 8: pos + 8 + 2 * words]
        pos += 8 + 2 * words
        if struct.unpack("<i", rec[:4])[0] == 0:                   # Null shape
            out.append((0.0, np.nan, np.nan))
            continue
        n_parts, n_points = struct.unpack("<ii", rec[36:44])
        parts = list(struct.unpack(f"<{n_parts}i", rec[44:44 + 4 * n_parts])) + [n_points]
        pts = np.frombuffer(rec, dtype="<f8", count=2 * n_points, offset=44 + 4 * n_parts).reshape(-1, 2)
        area = cx = cy = 0.0
        for a, b in pairwise(parts):
            x, y = pts[a:b, 0], pts[a:b, 1]
            x0, y0 = x - x[0], y - y[0]                            # 큰 좌표값의 자릿수 손실을 막으려고 고리 첫 점 기준
            cross = x0[:-1] * y0[1:] - x0[1:] * y0[:-1]
            ring = cross.sum() / 2
            if ring == 0:
                continue
            area += ring
            cx += ((x0[:-1] + x0[1:]) * cross).sum() / 6 + ring * x[0]
            cy += ((y0[:-1] + y0[1:]) * cross).sum() / 6 + ring * y[0]
        out.append((abs(area), cx / area, cy / area) if area else (0.0, np.nan, np.nan))
    return out


def read_dbf(dbf_path: str | Path, encoding: str = "cp949") -> pd.DataFrame:
    data = Path(dbf_path).read_bytes()
    n, header_len, record_len = struct.unpack("<IHH", data[4:12])
    fields = []
    for i in range(32, header_len - 1, 32):
        fields.append((data[i:i + 11].split(b"\0")[0].decode("ascii"), data[i + 16]))
    rows = []
    for r in range(n):
        rec = data[header_len + r * record_len + 1: header_len + (r + 1) * record_len]
        pos, row = 0, []
        for _, length in fields:
            row.append(rec[pos:pos + length].decode(encoding, "replace").strip())
            pos += length
        rows.append(row)
    return pd.DataFrame(rows, columns=[f for f, _ in fields])


def _read_csv_any(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)), dtype=str, keep_default_na=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: 인코딩을 알 수 없습니다")


def dong_keys(name: str) -> list[str]:
    """동 이름의 검색 키: '신촌동' → 신촌동·신촌, '역삼1동' → 역삼1동·역삼동·역삼, '명동1가' → 명동1가·명동, '명동' → 명동."""

    name = name.replace(" ", "")
    keys = [name]
    m = re.match(r"^(.+?)(\d+)?(동|가|리)$", name)
    if m:
        base, num, end = m.groups()
        if num:
            keys.append(base + end)                                # 역삼1동 → 역삼동, 명동1가 → 명동가(아래에서 명동)
        if end == "동" and len(base) >= 2:
            keys.append(base)                                      # 신촌동 → 신촌 (명동 → '명'은 한 글자라 뺌)
        if end == "가" and num and len(base) >= 2:
            keys.append(base)                                      # 명동1가 → 명동, 을지로3가 → 을지로
    return list(dict.fromkeys(k for k in keys if len(k) >= 2 and not k.endswith("동가")))


def station_keys(name: str) -> list[str]:
    """역 이름의 검색 키: '구의(광진구청)' → 구의·구의역·광진구청, '강촌역' → 강촌·강촌역."""

    name = name.replace(" ", "")
    alias = STATION_PAREN.findall(name)
    base = STATION_PAREN.sub("", name)
    base = base[:-1] if base.endswith("역") and len(base) >= 3 else base
    keys = [base, base + "역"] + [a for a in alias if len(a) >= 2]
    return list(dict.fromkeys(k for k in keys if len(k) >= 2))


def market_keys(name: str) -> list[str]:
    name = re.sub(r"\(.*?\)", "", name).replace(" ", "")
    keys = [name]
    for s in MARKET_SUFFIXES:
        if name.endswith(s) and len(name) - len(s) >= 2:
            keys.append(name[: -len(s)])                           # 남대문시장 → 남대문
            break
    return list(dict.fromkeys(k for k in keys if len(k) >= 2))


def build_gazetteer(src: str | Path, corpus: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    """공공데이터 원본 폴더 → 지명 사전 표. 열: key, name, kind, scope, sido_code, sigungu_code, code_prefix, lat, lon,
    center_source, source. key는 소문자·공백 없음(understanding의 지명 키와 같은 형식).
    corpus(legal_dong_code, latitude, longitude)를 주면 이름으로 못 이은 행정동(2026-07 개편된 인천 중구·동구·서구 등)의
    시군구를 3km 안 가장 가까운 가맹점의 법정동 코드로 채운다."""

    src = Path(src)
    bjd = _read_csv_any(src / "[행정안전부] 행정표준코드 법정동코드 정보.csv")
    bjd = bjd[bjd["법정동코드"].str.len() == 10]
    census = pd.read_excel(src / "센서스 공간정보 지역 코드.xlsx", sheet_name=0, dtype=str, header=1)
    shp = src / "BND_ADM_DONG_PG" / "BND_ADM_DONG_PG"
    adm = read_dbf(shp.with_suffix(".dbf"))
    geo = polygon_centroids(shp.with_suffix(".shp"))
    adm["area"], adm["x"], adm["y"] = zip(*geo, strict=True)
    adm["lat"], adm["lon"] = tm_to_wgs84(adm["x"], adm["y"])

    # 법정 시군구(5자리)와 이름 — 'OO시 OO구'는 구 단위, 'OO시'(구가 있는 시)는 city
    sgg = bjd[(bjd["읍면동코드"] == "000") & (bjd["시군구코드"] != "000")].copy()
    sgg["sido_name"] = sgg["지역주소명"].str.split().str[0]
    sgg["sgg_name"] = sgg["지역주소명"].str.split(n=1).str[1].fillna(sgg["sido_name"])   # 세종: 시군구 없음
    sgg["code5"] = sgg["법정동코드"].str[:5]
    by_name = {(r.sido_name, r.sgg_name): r.code5 for r in sgg.itertuples()}

    # SGIS 행정동 → 법정 시군구 코드(시도·시군구 이름으로 잇는다)
    census["sgis_sgg"] = census["시도코드"] + census["시군구코드"].str.zfill(3)
    census["sido_name"] = census["시도명칭"].map(lambda s: MERGED_SIDO.get(s, s))
    sgis_to_code5 = {}
    unmatched = set()
    for r in census.drop_duplicates("sgis_sgg").itertuples():
        code5 = by_name.get((r.sido_name, r.시군구명칭))
        only = sgg.loc[sgg["sido_name"] == r.sido_name, "code5"]
        if code5 is None and len(only) == 1:                       # 세종: 시도에 시군구가 하나
            code5 = only.iloc[0]
        if code5 is None:
            unmatched.add(f"{r.시도명칭} {r.시군구명칭}")
        else:
            sgis_to_code5[r.sgis_sgg] = code5
    adm["code5"] = adm["ADM_CD"].str[:5].map(sgis_to_code5)
    filled = 0
    if corpus is not None:
        clat, clon = corpus["latitude"].to_numpy(float), corpus["longitude"].to_numpy(float)
        ccode = corpus["legal_dong_code"].astype(str).str[:5].to_numpy()
        for i in adm.index[adm["code5"].isna() & adm["lat"].notna()]:
            d = np.hypot(clat - adm.at[i, "lat"], (clon - adm.at[i, "lon"]) * 0.8) * 111
            j = int(np.argmin(d))
            if d[j] <= 3.0:
                adm.at[i, "code5"] = ccode[j]
                filled += 1

    def weighted(g: pd.DataFrame) -> tuple[float, float]:
        w = g["area"].to_numpy()
        return float(np.average(g["lat"], weights=w)), float(np.average(g["lon"], weights=w))

    sgg_center = {k: weighted(g) for k, g in adm.dropna(subset=["code5"]).groupby("code5")}
    # 경계 데이터(2025-06) 뒤 새로 생긴 시군구(2026 화성시 4개 구 등)는 경계 중심이 없다 → 그 코드 가맹점 위치 중앙값으로 채운다
    store_center: dict[str, tuple[float, float]] = {}
    if corpus is not None:
        cc = corpus.assign(code5=corpus["legal_dong_code"].astype(str).str[:5])
        store_center = {k: (float(g["latitude"].median()), float(g["longitude"].median())) for k, g in cc.groupby("code5")}

    def center_of(code5: str) -> tuple[tuple[float, float], str]:
        """시군구 중심: 경계 → 가맹점 중앙값 → 옛 상위 시(구가 생기기 전 코드, 앞 4자리 + 0)의 경계."""

        if code5 in sgg_center:
            return sgg_center[code5], "polygon"
        if code5 in store_center:
            return store_center[code5], "corpus"
        return sgg_center.get(code5[:4] + "0", (np.nan, np.nan)), "parent"

    gu_parents = {c[:4] for c, n in zip(sgg["code5"], sgg["sgg_name"], strict=True) if len(str(n).split()) == 2}
    rows: list[dict] = []

    def add(keys, name, kind, scope, sido, code5, prefix, lat, lon, center_source, source):
        for k in keys:
            rows.append({"key": k.casefold(), "name": name, "kind": kind, "scope": scope, "sido_code": sido,
                         "sigungu_code": code5, "code_prefix": prefix, "lat": lat, "lon": lon,
                         "center_source": center_source, "source": source})

    # 시도
    for sido, g in adm.dropna(subset=["code5"]).groupby(adm["code5"].str[:2]):
        name = bjd.loc[bjd["법정동코드"] == sido + "00000000", "지역주소명"]
        if len(name):
            lat, lon = weighted(g)
            short = [s for s in SIDO_SHORT.get(name.iloc[0], []) if s not in OLD_METRO]
            add([name.iloc[0], *short], name.iloc[0], "sido", "area", sido, "", sido, lat, lon, "polygon", "법정동코드+SGIS")
    # 통합된 옛 광역시: '광주'는 전남광주통합특별시 전체가 아니라 옛 광주광역시(5개 구)다. code_prefix는 '|'로 여러 개
    for old, (sido, gus) in OLD_METRO.items():
        kids = sgg[(sgg["시도코드"] == sido) & sgg["sgg_name"].isin(gus)]
        cs = [sgg_center[c] for c in kids["code5"] if c in sgg_center]
        if cs:
            add([old, old + "광역시"], old + "광역시(2026-07 통합 전)", "city", "area", sido, sido, "|".join(kids["code5"]),
                float(np.mean([c[0] for c in cs])), float(np.mean([c[1] for c in cs])), "polygon", "법정동코드+SGIS")
    # 시군구·구가 있는 시
    for r in sgg.itertuples():
        words = r.sgg_name.split()
        if len(words) == 2:                                        # '성남시 분당구' → 분당구, 분당
            keys, kind, prefix = [words[1]] + ([words[1][:-1]] if len(words[1]) >= 3 else []), "sigungu", r.code5
        elif r.code5[:4] in gu_parents and r.code5.endswith("0"):  # 구가 있는 시(성남시, 2026 화성시): 법정동코드표 기준
            w = words[0]
            kids = sorted(c for c in sgg["code5"] if c[:4] == r.code5[:4] and c != r.code5)
            cs = [center_of(c)[0] for c in kids]
            cs = [c for c in cs if not np.isnan(c[0])] or [center_of(r.code5)[0]]
            add([w] + ([w[:-1]] if len(w) >= 3 else []), r.지역주소명, "city", "area", r.시도코드, r.code5, r.code5[:4],
                float(np.mean([c[0] for c in cs])), float(np.mean([c[1] for c in cs])), "polygon", "법정동코드+SGIS")
            continue
        else:
            w = words[0]
            keys, kind, prefix = [w] + ([w[:-1]] if len(w) >= 3 else []), "sigungu", r.code5
        (lat, lon), src_c = center_of(r.code5)
        add(keys, r.지역주소명, kind, "area", r.시도코드, r.code5, prefix, lat, lon, src_c, "법정동코드+SGIS")
    # 행정동
    hd_index: dict[tuple[str, str], tuple[float, float]] = {}
    for r in adm.dropna(subset=["code5"]).itertuples():
        add(dong_keys(r.ADM_NM), r.ADM_NM, "hdong", "point", r.code5[:2], r.code5, "", r.lat, r.lon, "polygon", "SGIS 행정동")
        for k in dong_keys(r.ADM_NM):
            hd_index.setdefault((r.code5, k), (r.lat, r.lon))
    # 법정 읍·면(넓음 → area)과 동(→ point). 동 중심: 같은 이름 행정동 → 없으면 시군구 중심(표시만, 거리 판단에 약함)
    emd = bjd[(bjd["읍면동코드"] != "000") & (bjd["리코드"] == "00")]
    for r in emd.itertuples():
        name = r.최하위지역명
        code5 = r.법정동코드[:5]
        if name.endswith(("읍", "면")):
            lat, lon = center_of(code5)[0]
            keys = [name] + ([name[:-1]] if len(name) >= 3 else [])
            add(keys, r.지역주소명, "eupmyeon", "area", r.시도코드, code5, r.법정동코드[:8], lat, lon, "sigungu", "법정동코드")
            continue
        keys = dong_keys(name)
        center = next((hd_index[(code5, k)] for k in keys if (code5, k) in hd_index), None)
        src_c = "hdong" if center else "sigungu"
        lat, lon = center or center_of(code5)[0]
        add(keys, r.지역주소명, "dong", "point", r.시도코드, code5, r.법정동코드[:8], lat, lon, src_c, "법정동코드")

    # 역·시장: 시군구는 가장 가까운 행정동의 것
    hd = adm.dropna(subset=["code5"])
    hlat, hlon, hcode = hd["lat"].to_numpy(), hd["lon"].to_numpy(), hd["code5"].to_numpy()

    def nearest_code5(lat: float, lon: float) -> str:
        return str(hcode[np.argmin((hlat - lat) ** 2 + ((hlon - lon) * 0.8) ** 2)])

    st = pd.read_excel(src / "전체_도시철도역사정보_20260630.xlsx", dtype=str)
    st["lat"], st["lon"] = pd.to_numeric(st["역위도"], errors="coerce"), pd.to_numeric(st["역경도"], errors="coerce")
    st = st.dropna(subset=["lat", "lon"])
    st["base"] = st["역사명"].map(lambda s: station_keys(s)[0])
    for base, g in st.groupby("base"):                             # 환승역·같은 이름 다른 노선은 1km 안이면 한 곳으로
        done: list[tuple[float, float]] = []
        for r in g.itertuples():
            if any(abs(r.lat - a) < 0.009 and abs(r.lon - b) < 0.011 for a, b in done):
                continue
            done.append((r.lat, r.lon))
            code5 = nearest_code5(r.lat, r.lon)
            add(station_keys(r.역사명), r.역사명, "station", "point", code5[:2], code5, "", r.lat, r.lon, "given",
                "도시철도역사정보")
    mk = _read_csv_any(src / "전국전통시장표준데이터.csv")
    mk["lat"], mk["lon"] = pd.to_numeric(mk["위도"], errors="coerce"), pd.to_numeric(mk["경도"], errors="coerce")
    for r in mk.dropna(subset=["lat", "lon"]).itertuples():
        code5 = nearest_code5(r.lat, r.lon)
        add(market_keys(r.시장명), r.시장명, "market", "point", code5[:2], code5, "", r.lat, r.lon, "given", "전통시장표준데이터")

    gaz = pd.DataFrame(rows).drop_duplicates(["key", "kind", "sigungu_code", "name"]).reset_index(drop=True)
    stats = {"rows": len(gaz), "kinds": gaz["kind"].value_counts().to_dict(), "sgis_unmatched_sigungu": sorted(unmatched),
             "hdong_code5_from_nearest_store": filled,
             "hdong_without_code5": int(adm["code5"].isna().sum()), "dong_center_from_sigungu":
             int(((gaz["kind"] == "dong") & (gaz["center_source"] == "sigungu")).sum())}
    return gaz, stats
