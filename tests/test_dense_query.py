from store_search_ai.data.service_pool import dense_query


def test_drops_region_words():
    assert dense_query("세종 모두의 미술학원", "세종") == "모두의 미술학원"
    assert dense_query("고암 디저트", "고암") == "디저트"
    assert dense_query("부산 신평시장 손칼국수", "부산 신평시장") == "손칼국수"


def test_keeps_query_without_region_or_when_nothing_left():
    assert dense_query("맥주 안주 파는 곳", "") == "맥주 안주 파는 곳"
    assert dense_query("석계역", "석계역") == "석계역"
    assert dense_query("세종모종", "세종") == "세종모종"   # 붙여 쓴 상호는 그대로(띄어 쓴 단어 단위)
