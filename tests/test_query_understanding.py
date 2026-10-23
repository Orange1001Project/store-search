import pandas as pd

from store_search_ai.query.understanding import QueryUnderstanding, place_keys


def _corpus():
    rows = [
        # 경기 안산 고잔동 — 숯토리
        ("숯토리", "한식", "경기도 안산시 단원구 광덕3로 167 (고잔동)", "도리섬상점가", "경기도", "4127310100", 37.31, 126.83),
        ("고잔식당", "한식", "경기도 안산시 단원구 광덕3로 160 (고잔동)", "도리섬상점가", "경기도", "4127310100", 37.31, 126.83),
        # 순천 웃장
        ("순천손두부", "두부", "전라남도 순천시 북문길 40(동외동)", "웃장", "전라남도", "4615012200", 34.95, 127.49),
        # 같은 이름 '신림': 서울 신림동(가게 많음) vs 원주 신림면(적음)
        *[(f"서울가게{i}", "의류", "서울특별시 관악구 신림로 1 (신림동)", "신림중앙시장", "서울특별시", "1162010200", 37.48, 126.93)
          for i in range(3)],
        ("원주가게", "의류", "강원특별자치도 원주시 신림면 신림로 1", "", "강원특별자치도", "5113036000", 37.23, 128.08),
        # 체인
        *[(f"GS25 {n}점", "편의점", "서울특별시 관악구 신림로 2 (신림동)", "", "서울특별시", "1162010200", 37.48, 126.93)
          for n in ("신림", "봉천", "서원")],
        # 상품어와 겹치는 동 이름: 우산동
        ("우산동마트", "마트", "광주광역시 광산구 우산로 1 (우산동)", "", "광주광역시", "2920010100", 35.17, 126.81),
    ]
    rows += [(f"우산가게{i}", "우산 양산", "서울특별시 중구 명동길 1 (명동1가)", "", "서울특별시", "1114010100", 37.56, 126.98)
             for i in range(25)]
    return pd.DataFrame(rows, columns=["store_name", "item_text", "address", "market_name", "source_region", "legal_dong_code",
                                       "latitude", "longitude"])


def test_place_keys_admin_local_and_market():
    admin, local = place_keys("경기도 성남시 분당구 정자로 1 (정자동)", "정자 골목형상점가", "경기도")
    assert {"경기", "성남시", "성남", "분당구", "분당"} <= admin
    assert {"정자동", "정자", "정자로"} <= local
    _, local = place_keys("서울특별시 중구 명동길 1 (명동1가)", "", "서울특별시")
    assert "명동" in local                                     # 명동1가 → 명동


def test_region_and_name_split():
    qu = QueryUnderstanding(_corpus())
    p = qu.parse("안산 고잔 숯토리", 37.31, 126.83)
    assert p.region_text == "안산 고잔" and p.core == "숯토리" and p.intent == "name"
    p = qu.parse("순천 웃장 손두부", 34.95, 127.49)
    assert p.region_text == "순천 웃장" and p.core == "손두부"


def test_product_word_is_not_a_place_and_generic_rest():
    qu = QueryUnderstanding(_corpus())
    assert qu.parse("우산 파는 곳").region is None               # 상품어 + 일반어만 남음
    assert qu.parse("우산 양산").region is None                  # '우산'은 취급품목에 20곳 이상
    assert qu.parse("우산동 마트").region_text == "우산동"        # 끝말을 붙이면 지명


def test_ambiguous_place_near_user_else_largest():
    qu = QueryUnderstanding(_corpus())
    near_wonju = qu.parse("신림 옷가게", 37.23, 128.08)
    assert set(qu.corpus.loc[near_wonju.region.doc_idx, "store_name"]) == {"원주가게"}
    far = qu.parse("신림 옷가게", 35.18, 129.07)                 # 부산 사용자 → 가게가 많은 서울 신림
    assert "원주가게" not in set(qu.corpus.loc[far.region.doc_idx, "store_name"])


def test_metropolitan_city_is_not_split_by_gu():
    rows = [(f"가게{i}", "한식", f"대전광역시 {gu} 대흥로 1 (대흥동)", "", "대전광역시", code, 36.33, 127.42)
            for i, (gu, code) in enumerate([("중구", "3014010100"), ("서구", "3017010100"), ("유성구", "3020010100")])]
    rows.append(("대전동가게", "한식", "경상북도 영천시 대전동 1", "", "경상북도", "4723010100", 35.97, 128.94))
    qu = QueryUnderstanding(pd.DataFrame(rows, columns=["store_name", "item_text", "address", "market_name", "source_region",
                                                        "legal_dong_code", "latitude", "longitude"]))
    p = qu.parse("대전 신라혼수방", 37.57, 126.98)                 # 서울 사용자
    assert len(p.region.doc_idx) == 3                              # 대전광역시 전체(구 3개)


def test_brand_and_category_intent():
    qu = QueryUnderstanding(_corpus())
    assert qu.parse("GS25").intent == "brand"
    assert qu.parse("의류").intent == "category"
