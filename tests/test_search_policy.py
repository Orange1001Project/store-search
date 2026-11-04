import yaml

from store_search_ai.query import understanding


def test_policy_values_match_parser_constants():
    """정책 파일(백엔드로 넘기는 값)과 쿼리 이해 코드의 상수가 어긋나지 않게 한다."""

    with open("configs/service/search_policy_v1.yaml", encoding="utf-8") as f:
        policy = yaml.safe_load(f)
    assert policy["radius"]["first_km"] == understanding.POINT_KM
    assert policy["region"]["near_km"] == understanding.NEAR_KM
    assert policy["region"]["name_first_km"] == understanding.NAME_FIRST_KM
    assert policy["region"]["gazetteer"] == understanding.GAZETTEER_PATH
    assert set(policy["region"]["area_kinds"]) == set(understanding.AREA_KINDS)
