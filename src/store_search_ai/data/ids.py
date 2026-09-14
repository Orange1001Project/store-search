from __future__ import annotations

import hashlib


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
            business_no or "",
            (store_name or "").casefold(),
            (address or "").casefold(),
        ]
    )

    return hashlib.sha256(
        key.encode("utf-8")
    ).hexdigest()