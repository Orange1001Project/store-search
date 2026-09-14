from store_search_ai.data.text_cleaning import clean_address
from store_search_ai.data.items import parse_item_tokens
from store_search_ai.data.ids import build_entity_fingerprint

def test_address():
    clean,flags=clean_address('대전광역시 중구 예시로 31\xa0\xa0<br>'); assert clean=='대전광역시 중구 예시로 31'; assert flags['address_had_html_break']; assert flags['address_had_nbsp']
def test_items():
    assert parse_item_tokens(None)==[]; assert parse_item_tokens('면류, 건어물')==['면류','건어물']
def test_id_stable():
    assert build_entity_fingerprint('1','가게','주소')==build_entity_fingerprint('1','가게','주소')
