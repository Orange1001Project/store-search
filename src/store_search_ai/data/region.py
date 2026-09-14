from __future__ import annotations

import pandas as pd


def normalize_region(
    address: object,
    aliases: dict[str, str],
) -> tuple[str | None, str]:
    """
    주소 첫 토큰(시도)을 표준 시도명으로 정규화한다.

    Returns
    -------
    (region, status) — status는 "VALID" 또는 "UNMAPPED".
    주소가 없거나 첫 토큰이 alias 테이블에 없으면 (None, "UNMAPPED")를 반환한다
    (market_type_status=UNMAPPED과 동일한 원칙: 조용히 통과시키되 플래그로 남긴다).
    """

    if address is None or pd.isna(address):
        return None, "UNMAPPED"

    text = str(address).strip()

    if not text:
        return None, "UNMAPPED"

    first_token = text.split()[0]

    region = aliases.get(first_token)

    if region is None:
        return None, "UNMAPPED"

    return region, "VALID"


def derive_region_series(
    address: pd.Series,
    aliases: dict[str, str],
) -> tuple[pd.Series, pd.Series]:
    """
    주소 Series 전체에 normalize_region을 적용해
    (region Series, status Series) 튜플로 반환한다.
    """

    pairs = address.map(
        lambda value: normalize_region(value, aliases)
    )

    region = pairs.map(lambda x: x[0])
    status = pairs.map(lambda x: x[1])

    return region, status
