from __future__ import annotations

import json

import pandas as pd


def _unique_non_null(series: pd.Series) -> list:
    """
    순서를 최대한 유지하면서 NULL을 제외한 unique 값 반환.
    """

    values = []

    for value in series:

        if value is None:
            continue

        try:
            if pd.isna(value):
                continue
        except (TypeError, ValueError):
            pass

        if value not in values:
            values.append(value)

    return values


def _merge_item_tokens(
    series: pd.Series,
) -> list[str]:

    result: list[str] = []

    for tokens in series:

        if not isinstance(tokens, (list, tuple)):
            continue

        for token in tokens:

            if token not in result:
                result.append(token)

    return result


def _coordinate_candidates(
    group: pd.DataFrame,
) -> list[dict]:

    candidates = []

    for lat, lon in zip(
        group["latitude"],
        group["longitude"],
    ):

        if pd.isna(lat) or pd.isna(lon):
            continue

        candidate = {
            "latitude": float(lat),
            "longitude": float(lon),
        }

        if candidate not in candidates:
            candidates.append(candidate)

    return candidates


def build_store_master(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Source records 여러 개를 store_id 기준 하나의 Store Master로 병합.

    원칙
    ----
    1. store_id는 변경하지 않는다.
    2. item은 합집합.
    3. merchant_no 충돌은 임의 선택하지 않는다.
    4. 서로 다른 유효 좌표가 존재하면 임의 선택하지 않는다.
    5. 결제 여부 충돌도 임의 판단하지 않는다.
    6. 모든 source lineage를 master에 남긴다.
    """

    master_rows = []
    conflict_rows = []

    for store_id, group in df.groupby(
        "store_id",
        sort=False,
    ):

        group = group.sort_values(
            "source_record_key"
        )

        # 첫 행을 기본 template으로 사용
        row = group.iloc[0].copy()

        # ---------------------------------------------
        # Source lineage
        # ---------------------------------------------

        source_keys = (
            group["source_record_key"]
            .astype(str)
            .tolist()
        )

        row["source_record_count"] = len(group)

        row["source_record_keys"] = (
            source_keys
        )

        # ---------------------------------------------
        # 취급품목
        #
        # 같은 매장에 다른 품목이 있으면 합집합
        # ---------------------------------------------

        merged_tokens = _merge_item_tokens(
            group["item_tokens"]
        )

        row["item_tokens"] = merged_tokens

        row["item_text"] = (
            ", ".join(merged_tokens)
            if merged_tokens
            else None
        )

        row["has_item"] = bool(
            merged_tokens
        )

        item_raw_variants = (
            _unique_non_null(
                group["item_raw"]
            )
        )

        row[
            "item_raw_variants"
        ] = item_raw_variants

        row[
            "item_conflict"
        ] = (
            len(item_raw_variants) > 1
        )

        if len(item_raw_variants) > 1:

            conflict_rows.append(
                {
                    "store_id": store_id,
                    "field": "item",
                    "values": json.dumps(
                        item_raw_variants,
                        ensure_ascii=False,
                    ),
                    "source_record_keys":
                        "|".join(source_keys),
                }
            )

        # ---------------------------------------------
        # merchant_no
        # ---------------------------------------------

        merchant_candidates = (
            _unique_non_null(
                group["merchant_no"]
            )
        )

        row[
            "merchant_no_candidates"
        ] = merchant_candidates

        row[
            "merchant_no_conflict"
        ] = (
            len(merchant_candidates) > 1
        )

        if len(merchant_candidates) == 1:

            row["merchant_no"] = (
                merchant_candidates[0]
            )

        elif len(merchant_candidates) == 0:

            row["merchant_no"] = pd.NA

        else:

            # 어느 번호가 최신/정확한지 모르므로
            # master primary 값은 비움
            row["merchant_no"] = pd.NA

            conflict_rows.append(
                {
                    "store_id": store_id,
                    "field": "merchant_no",
                    "values": json.dumps(
                        merchant_candidates,
                        ensure_ascii=False,
                    ),
                    "source_record_keys":
                        "|".join(source_keys),
                }
            )

        # ---------------------------------------------
        # 좌표
        # ---------------------------------------------

        geo_candidates = (
            _coordinate_candidates(
                group
            )
        )

        row["geo_candidates"] = [
            f"{x['latitude']},{x['longitude']}"
            for x in geo_candidates
        ]

        row["geo_conflict"] = (
            len(geo_candidates) > 1
        )

        if len(geo_candidates) == 1:

            row["latitude"] = (
                geo_candidates[0][
                    "latitude"
                ]
            )

            row["longitude"] = (
                geo_candidates[0][
                    "longitude"
                ]
            )

        elif len(geo_candidates) == 0:

            row["latitude"] = pd.NA
            row["longitude"] = pd.NA

        else:

            # 서로 다른 정상 좌표가 여러 개라면
            # 잘못된 것을 임의 선택하지 않는다.
            row["latitude"] = pd.NA
            row["longitude"] = pd.NA

            row["geo_status"] = (
                "CONFLICT"
            )

            conflict_rows.append(
                {
                    "store_id": store_id,
                    "field": "geo",
                    "values": json.dumps(
                        geo_candidates,
                        ensure_ascii=False,
                    ),
                    "source_record_keys":
                        "|".join(source_keys),
                }
            )

        # ---------------------------------------------
        # Card payment
        # ---------------------------------------------

        card_values = (
            _unique_non_null(
                group["card_payment"]
            )
        )

        row[
            "card_payment_conflict"
        ] = (
            len(card_values) > 1
        )

        if len(card_values) == 1:

            row["card_payment"] = (
                card_values[0]
            )

        elif len(card_values) > 1:

            row["card_payment"] = pd.NA

            conflict_rows.append(
                {
                    "store_id": store_id,
                    "field": "card_payment",
                    "values": str(card_values),
                    "source_record_keys":
                        "|".join(source_keys),
                }
            )

        # ---------------------------------------------
        # Mobile payment
        # ---------------------------------------------

        mobile_values = (
            _unique_non_null(
                group[
                    "mobile_payment"
                ]
            )
        )

        row[
            "mobile_payment_conflict"
        ] = (
            len(mobile_values) > 1
        )

        if len(mobile_values) == 1:

            row[
                "mobile_payment"
            ] = mobile_values[0]

        elif len(mobile_values) > 1:

            # Y/N 중 무엇이 맞는지 확인 불가능
            row[
                "mobile_payment"
            ] = pd.NA

            conflict_rows.append(
                {
                    "store_id": store_id,
                    "field": "mobile_payment",
                    "values": str(
                        mobile_values
                    ),
                    "source_record_keys":
                        "|".join(source_keys),
                }
            )

        master_rows.append(row)

    master = pd.DataFrame(
        master_rows
    ).reset_index(
        drop=True
    )

    conflicts = pd.DataFrame(
        conflict_rows
    )

    return master, conflicts