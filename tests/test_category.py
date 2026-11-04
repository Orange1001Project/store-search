from store_search_ai.data.category import Category, assign

TAX = [Category("AUTO", "자동차 교통", ("자동차",)),
       Category("BEAUTY", "미용", ("미용",)),
       Category("LIFE", "생활서비스", ("애견미용",)),
       Category("CLOTHING", "의류", ("운동화", "가방")),
       Category("SPORTS", "스포츠", ("운동",)),
       Category("CAFE", "카페 디저트", ("커피", "차"), ("카페",)),
       Category("FOOD", "식품 마트", ("식품", "떡")),
       Category("LIVING", "생활 잡화", ("장식품",)),
       Category("MEDICAL", "의료", ("약국",), ("약국",)),
       Category("ETC", "기타", ())]


def test_one_char_keywords_match_whole_words_only():
    assert assign("자동차 부품", "", TAX)[0] == "AUTO"            # '자동차'의 '차'는 카페가 아니다
    assert assign("커피, 차", "", TAX)[1] == ["CAFE"]
    assert assign("떡, 한과", "", TAX)[0] == "FOOD" and assign("떡볶이", "", TAX)[0] == "ETC"


def test_contained_short_keyword_is_dropped_and_first_wins():
    assert assign("애견미용", "", TAX)[1] == ["LIFE"]             # '애견미용' 안의 '미용'은 버린다
    assert assign("운동화, 가방", "", TAX)[0] == "CLOTHING"        # '운동화' 안의 '운동'은 스포츠가 아니다
    assert assign("소매(장식품)", "", TAX)[0] == "LIVING"           # '장식품' 안의 '식품'
    assert assign("커피, 운동", "", TAX) == ("CAFE", ["CAFE", "SPORTS"], "item")


def test_store_name_fallback_and_etc():
    assert assign("", "행복약국", TAX) == ("MEDICAL", ["MEDICAL"], "name")
    assert assign(None, "무명상점", TAX) == ("ETC", ["ETC"], "none")
