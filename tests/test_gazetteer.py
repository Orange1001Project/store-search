import struct

import pandas as pd

from store_search_ai.data.gazetteer import (
    dong_keys,
    market_keys,
    polygon_centroids,
    station_keys,
    tm_to_wgs84,
)
from store_search_ai.query.understanding import QueryUnderstanding


def test_tm_inverse_origin_and_known_point():
    lat, lon = tm_to_wgs84([200000.0], [600000.0])                 # EPSG:5186 원점
    assert abs(lat[0] - 38.0) < 1e-9 and abs(lon[0] - 127.0) < 1e-9
    # 서울시청 부근(EPSG:5186 약 (197980, 551900)) → 37.566, 126.977 근처
    lat, lon = tm_to_wgs84([197980.0], [551900.0])
    assert abs(lat[0] - 37.5664) < 0.002 and abs(lon[0] - 126.9772) < 0.002


def test_polygon_centroid_of_square(tmp_path):
    pts = [(0, 0), (0, 2), (2, 2), (2, 0), (0, 0)]
    content = struct.pack("<i4d2i", 5, 0, 0, 2, 2, 1, len(pts)) + struct.pack("<i", 0) + b"".join(struct.pack("<2d", *p) for p in pts)
    shp = tmp_path / "a.shp"
    shp.write_bytes(b"\0" * 100 + struct.pack(">ii", 1, len(content) // 2) + content)
    (area, cx, cy), = polygon_centroids(shp)
    assert area == 4 and cx == 1 and cy == 1


def test_place_name_keys():
    assert dong_keys("신촌동") == ["신촌동", "신촌"]
    assert dong_keys("역삼1동") == ["역삼1동", "역삼동", "역삼"]
    assert dong_keys("명동1가") == ["명동1가", "명동"]
    assert dong_keys("명동") == ["명동"]                             # '명' 한 글자는 키로 쓰지 않음
    assert station_keys("구의(광진구청)") == ["구의", "구의역", "광진구청"]
    assert station_keys("강촌역") == ["강촌", "강촌역"]
    assert market_keys("남대문시장") == ["남대문시장", "남대문"]


def _gaz(rows):
    cols = ["key", "name", "kind", "scope", "sido_code", "sigungu_code", "code_prefix", "lat", "lon", "center_source", "source"]
    return pd.DataFrame(rows, columns=cols)


def _corpus(rows):
    return pd.DataFrame(rows, columns=["store_name", "item_text", "address", "market_name", "source_region", "legal_dong_code",
                                       "latitude", "longitude"])


SEOUL_SINCHON = (37.564, 126.942)
DAEJEON = (36.33, 127.42)


def _sinchon():
    # 창원 신촌동: 가맹점이 많음. 서울 신촌: 가맹점은 적지만 행정동·법정동·역이 있음
    corpus = _corpus([*[(f"창원가게{i}", "한식", "경상남도 창원시 성산구 신촌로 1 (신촌동)", "", "경상남도", "4812312300", 35.20, 128.67)
                        for i in range(6)],
                      ("연세가게", "카페", "서울특별시 서대문구 연세로 1 (창천동)", "", "서울특별시", "1141011100", 37.558, 126.937),
                      ("신촌설렁탕", "한식", "충청남도 공주시 산성시장3길 34", "", "충청남도", "4415010100", 36.46, 127.12),
                      *[(f"대전가게{i}", "한식", "대전광역시 중구 대흥로 1 (대흥동)", "", "대전광역시", "3014010100", 36.33, 127.42)
                        for i in range(3)]])
    gaz = _gaz([("신촌동", "신촌동", "hdong", "point", "11", "11410", "", *SEOUL_SINCHON, "polygon", "SGIS"),
                ("신촌", "신촌동", "hdong", "point", "11", "11410", "", *SEOUL_SINCHON, "polygon", "SGIS"),
                ("신촌", "서울특별시 서대문구 신촌동", "dong", "point", "11", "11410", "11410114", *SEOUL_SINCHON, "hdong", "법정동"),
                ("신촌", "신촌", "station", "point", "11", "11440", "", 37.555, 126.937, "given", "도시철도"),
                ("신촌", "경상남도 창원시 성산구 신촌동", "dong", "point", "48", "48123", "48123123", 35.2, 128.67, "sigungu", "법정동"),
                ("신촌", "대전광역시 동구 신촌동", "dong", "point", "30", "30110", "30110131", 36.32, 127.47, "sigungu", "법정동"),
                ("중구", "대전광역시 중구", "sigungu", "area", "30", "30140", "30140", 36.28, 127.41, "polygon", "법정동"),
                ("중구", "서울특별시 중구", "sigungu", "area", "11", "11140", "11140", 37.56, 127.0, "polygon", "법정동")])
    return QueryUnderstanding(corpus, gazetteer=gaz)


def test_ambiguous_place_prefers_near_then_public_evidence():
    qu = _sinchon()
    # 대전 사용자: 대전 동구 신촌동은 좌표 근거가 없는 법정동(가게·행정동 없음)이라 '근처'로 고르지 않는다 → 근거 갈래가 많은
    # 서울 신촌(서대문 행정동 + 3km 안 마포 신촌역 = 행정구역·역 두 갈래)이 가맹점이 많은 창원 신촌동(행정구역 한 갈래)보다 앞선다
    p = qu.parse("신촌 설렁탕", *DAEJEON)
    assert p.region.center[0] > 37.5 and p.region.scope == "point"
    assert {a[0] for a in p.region.alternatives} >= {"경상남도 창원시 성산구 신촌동"}
    # 창원 사용자: 근처 우선
    p = qu.parse("신촌 설렁탕", 35.2, 128.67)
    assert p.region.center[0] < 36
    # 시군구 이름: 사용자 위치의 중구, 지역 안 가게는 코드 앞자리로
    p = qu.parse("중구 치킨", *DAEJEON)
    assert p.region.scope == "area" and p.region.code_prefix == "30140" and len(p.region.doc_idx) == 3


def test_name_first_when_store_named_like_query_is_near():
    qu = _sinchon()
    assert qu.parse("신촌 설렁탕", 36.46, 127.12).name_first          # 공주 신촌설렁탕 앞: 상호 검색 먼저
    assert not qu.parse("신촌 설렁탕", *DAEJEON).name_first           # 10km 밖이면 지역 해석
    assert qu.parse("신촌 설렁탕", *DAEJEON).name_key == "신촌 설렁탕"  # 상호 일치 가산점은 그대로


def test_chained_place_must_be_inside_previous():
    corpus = _corpus([*[(f"가게{i}", "한식", "대전광역시 중구 대흥로 1 (대흥동)", "", "대전광역시", "3014010100", 36.33, 127.42)
                        for i in range(3)],
                      ("아카데미문구", "문구", "경상북도 영천시 아카데미로 1 (대전동)", "", "경상북도", "4723012000", 36.0, 128.94)])
    gaz = _gaz([("대전", "대전광역시", "sido", "area", "30", "", "30", 36.34, 127.39, "polygon", "법정동"),
                ("대전", "경상북도 영천시 대전동", "dong", "point", "47", "47230", "47230120", 36.0, 128.94, "sigungu", "법정동")])
    qu = QueryUnderstanding(corpus, gazetteer=gaz)
    p = qu.parse("대전 아카데미 과학모형", *DAEJEON)
    assert p.region_text == "대전"                                   # 영천 '아카데미로'는 대전 안이 아니다


def test_old_metro_city_uses_several_code_prefixes():
    corpus = _corpus([("광산가게", "떡갈비", "전남광주통합특별시 광산구 1", "", "광주광역시", "1233010100", 35.14, 126.79),
                      ("목포가게", "떡갈비", "전남광주통합특별시 목포시 1", "", "전라남도", "1211010100", 34.8, 126.4),
                      ("경기광주가게", "떡갈비", "경기도 광주시 1", "", "경기도", "4161010100", 37.4, 127.25)])
    gaz = _gaz([("광주", "광주광역시(2026-07 통합 전)", "city", "area", "12", "12", "12330|12240", 35.14, 126.85, "polygon", "법정동"),
                ("광주", "경기도 광주시", "sigungu", "area", "41", "41610", "41610", 37.4, 127.3, "polygon", "법정동")])
    qu = QueryUnderstanding(corpus, gazetteer=gaz)
    p = qu.parse("광주 떡갈비", 37.56, 126.94)                         # 서울 사용자(경기 광주는 30km 밖)
    assert set(qu.corpus.loc[p.region.doc_idx, "store_name"]) == {"광산가게"}   # 목포(전남)는 '광주'가 아니다


def test_near_place_without_stores_is_not_chosen_by_proximity():
    corpus = _corpus([*[(f"장흥가게{i}", "보일러", "전남광주통합특별시 장흥군 장흥읍 1", "", "전라남도", "1280025000", 34.68, 126.91)
                        for i in range(3)],
                      ("서울가게", "한식", "서울특별시 중구 세종대로 1", "", "서울특별시", "1114010100", 37.566, 126.978)])
    gaz = _gaz([("장흥", "전남광주통합특별시 장흥군", "sigungu", "area", "12", "12800", "12800", 34.68, 126.92, "polygon", "법정동"),
                ("장흥면", "경기도 양주시 장흥면", "eupmyeon", "area", "41", "41630", "41630340", 37.72, 126.95, "sigungu", "법정동"),
                ("장흥", "경기도 양주시 장흥면", "eupmyeon", "area", "41", "41630", "41630340", 37.72, 126.95, "sigungu", "법정동")])
    qu = QueryUnderstanding(corpus, gazetteer=gaz)
    p = qu.parse("장흥 보일러", 37.566, 126.978)                      # 서울 사용자: 양주 장흥면은 가깝지만 가맹점이 없다
    assert p.region.code_prefix == "12800"


def test_corpus_only_area_from_address_code_mismatch_is_dropped():
    # 주소는 '대전광역시 동구'인데 법정동 코드는 대덕구(30230)인 가게 하나가 사용자 근처에 있어도 동구는 대전 동구(30110)
    corpus = _corpus([*[(f"동구가게{i}", "국밥", "대전광역시 동구 중앙로 1", "", "대전광역시", "3011010100", 36.33, 127.43)
                        for i in range(3)],
                      ("어긋난가게", "국밥", "대전광역시 동구 오정로 1", "", "대전광역시", "3023010100", 36.384, 127.32)])
    gaz = _gaz([("동구", "대전광역시 동구", "sigungu", "area", "30", "30110", "30110", 36.32, 127.47, "polygon", "법정동")])
    qu = QueryUnderstanding(corpus, gazetteer=gaz)
    assert qu.parse("동구 국밥", 36.3832, 127.3192).region.code_prefix == "30110"
