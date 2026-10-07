from __future__ import annotations

import hashlib

import pandas as pd


def _clean(value: object) -> str:
    """엑셀의 빈 셀은 문자열이 아니라 float NaN으로 들어온다 — NaN은 파이썬에서
    truthy라서 `value or ""`로는 걸러지지 않는다(`.casefold()` 호출 시 AttributeError)."""

    if value is None or pd.isna(value):
        return ""
    return str(value)


def build_entity_fingerprint(
    business_no: str | None,
    store_name: str | None,
    address: str | None,
) -> str:
    """
    동일 매장 후보를 식별하기 위한 fingerprint.

    주의:
    이것은 영구 PK(store_id)가 아니다.
    store_id는 별도의 registry에서 UUID로 발급한다.
    """

    key = "|".join(
        [
            _clean(business_no),
            _clean(store_name).casefold(),
            _clean(address).casefold(),
        ]
    )

    return hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()