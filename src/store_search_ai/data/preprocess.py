from __future__ import annotations

import pandas as pd

from .text_cleaning import (
    normalize_spaces,
    clean_address,
    clean_digits,
    normalize_yn,
)

from .ids import (
    build_entity_fingerprint,
)

from .items import (
    parse_item_tokens,
    has_ambiguous_suffix,
)

from .region import (
    derive_region_series,
)


def canonicalize(
    df: pd.DataFrame,
    config: dict,
    source_file: str,
    source_sheet: str,
    source_region: str | None,
) -> pd.DataFrame:

    # --------------------------------------------------
    # 1. 필수 컬럼 검사
    # --------------------------------------------------

    missing = [
        column
        for column in config["required_raw_columns"]
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"Missing required columns: {missing}"
        )

    # 원본 dataframe 복사
    w = df.copy()

    # optional column이 없으면 생성
    for column in config.get(
        "optional_raw_columns",
        [],
    ):
        if column not in w.columns:
            w[column] = pd.NA

    # 한글 원본 컬럼명 → 내부 컬럼명
    w = w.rename(
        columns=config["column_map"]
    )

    out = pd.DataFrame(
        index=w.index
    )

    # --------------------------------------------------
    # 2. Raw 값 보존
    # --------------------------------------------------

    raw_columns = [
        "source_row_no_raw",
        "store_name_raw",
        "business_no_raw",
        "merchant_no_raw",
        "address_raw",
        "latitude_raw",
        "longitude_raw",
        "legal_dong_code_raw",
        "market_type_raw",
        "market_name_raw",
        "item_raw",
    ]

    for column in raw_columns:
        out[column] = w[column]

    # --------------------------------------------------
    # 3. Lineage 정보
    # --------------------------------------------------

    out["source_file"] = source_file
    out["source_sheet"] = source_sheet

    # 새 전국 데이터처럼 "No." 컬럼 자체가 없는 경우도 있다.
    # 그런 경우(또는 값이 결측인 경우) 시트 내 순서를 1부터
    # 매겨 source_record_key가 항상 유일하도록 보정한다.
    row_no = pd.to_numeric(
        w["source_row_no_raw"],
        errors="coerce",
    )

    missing_row_no = row_no.isna()

    if missing_row_no.any():

        positional = pd.Series(
            range(1, len(w) + 1),
            index=w.index,
            dtype="Float64",
        )

        row_no = row_no.where(
            ~missing_row_no,
            positional,
        )

    out["source_row_no"] = row_no.astype("Int64")

    out["source_record_key"] = (
        source_file
        + ":"
        + source_sheet
        + ":"
        + out["source_row_no"].astype("string")
    )

    # 예:
    # stores.xlsx:대전가맹점:127

    # --------------------------------------------------
    # 4. 기본 문자열 정제
    # --------------------------------------------------

    out["store_name"] = (
        w["store_name_raw"]
        .map(normalize_spaces)
    )

    out["business_no"] = (
        w["business_no_raw"]
        .map(clean_digits)
    )

    out["merchant_no"] = (
        w["merchant_no_raw"]
        .map(clean_digits)
    )

    out["legal_dong_code"] = (
        w["legal_dong_code_raw"]
        .map(clean_digits)
    )

    out["market_name"] = (
        w["market_name_raw"]
        .map(normalize_spaces)
    )

    # --------------------------------------------------
    # 5. 주소 정제
    # --------------------------------------------------

    cleaned_address = (
        w["address_raw"]
        .map(clean_address)
    )

    out["address"] = (
        cleaned_address
        .map(lambda x: x[0])
    )

    out["address_had_html_break"] = (
        cleaned_address
        .map(
            lambda x:
            x[1]["address_had_html_break"]
        )
    )

    out["address_had_nbsp"] = (
        cleaned_address
        .map(
            lambda x:
            x[1]["address_had_nbsp"]
        )
    )

    out[
        "address_repeated_parenthetical"
    ] = (
        cleaned_address
        .map(
            lambda x:
            x[1][
                "address_repeated_parenthetical"
            ]
        )
    )

    # --------------------------------------------------
    # 5b. 지역(시도) 판별
    #
    # 시트에 source_region이 고정값으로 주어지면(레거시 다중 시트 파일)
    # 그 값을 그대로 쓰고, 없으면(전국 단일 시트) 정제된 주소에서
    # 시도를 파생한다.
    # --------------------------------------------------

    if source_region is not None:

        out["source_region"] = source_region
        out["source_region_status"] = "VALID"

    else:

        region, region_status = derive_region_series(
            out["address"],
            config["region_aliases"],
        )

        out["source_region"] = region
        out["source_region_status"] = region_status

    # --------------------------------------------------
    # 6. 좌표 처리
    #
    # 원본 데이터에서 0,0은
    # 실제 위치가 아니라 missing 표현으로 확인됨
    # --------------------------------------------------

    latitude = pd.to_numeric(
        w["latitude_raw"],
        errors="coerce",
    )

    longitude = pd.to_numeric(
        w["longitude_raw"],
        errors="coerce",
    )

    zero_coordinate = (
        (latitude == 0)
        & (longitude == 0)
    )

    out[
        "geo_zero_coordinate"
    ] = zero_coordinate

    # 0,0 → NULL
    out["latitude"] = latitude.mask(
        zero_coordinate
    )

    out["longitude"] = longitude.mask(
        zero_coordinate
    )

    # --------------------------------------------------
    # 7. 좌표 validation
    # --------------------------------------------------

    validation = config["validation"]

    out["invalid_latitude"] = ~(
        out["latitude"]
        .between(
            validation["latitude_min"],
            validation["latitude_max"],
        )
    )

    out["invalid_longitude"] = ~(
        out["longitude"]
        .between(
            validation["longitude_min"],
            validation["longitude_max"],
        )
    )

    # 기본 상태
    out["geo_status"] = "VALID"

    # 원본 0,0
    out.loc[
        zero_coordinate,
        "geo_status",
    ] = "MISSING_ZERO"

    # 0,0 이외의 비정상좌표
    invalid_geo = (
        (
            out["invalid_latitude"]
            | out["invalid_longitude"]
        )
        & ~zero_coordinate
    )

    out.loc[
        invalid_geo,
        "geo_status",
    ] = "INVALID"

    # --------------------------------------------------
    # 8. 법정동코드 / 사업자번호 validation
    # --------------------------------------------------

    out[
        "invalid_legal_dong_code"
    ] = ~(
        out["legal_dong_code"]
        .fillna("")
        .str.fullmatch(
            rf"\d{{{validation['legal_dong_code_length']}}}"
        )
    )

    out[
        "invalid_business_no_shape"
    ] = ~(
        out["business_no"]
        .fillna("")
        .str.fullmatch(
            rf"\d{{{validation['business_no_length']}}}"
        )
    )

    # --------------------------------------------------
    # 9. 시장분류 처리
    # --------------------------------------------------

    # 원본 의미를 보존하면서 공백만 정리
    market_type_clean = (
        w["market_type_raw"]
        .map(normalize_spaces)
    )

    valid_market_types = set(
        config["valid_market_types"]
    )

    market_type_valid = (
        market_type_clean
        .isin(valid_market_types)
    )

    # 정상값만 실제 market_type에 사용
    out["market_type"] = (
        market_type_clean
        .where(market_type_valid)
    )

    out[
        "market_type_status"
    ] = "VALID"

    out.loc[
        ~market_type_valid,
        "market_type_status",
    ] = "UNMAPPED"

    # '8' 같은 값은
    #
    # market_type_raw = 8
    # market_type = NULL
    # market_type_status = UNMAPPED

    # --------------------------------------------------
    # 10. 결제
    # --------------------------------------------------

    out["card_payment"] = (
        w["card_payment_raw"]
        .map(normalize_yn)
        .astype("boolean")
    )

    out["mobile_payment"] = (
        w["mobile_payment_raw"]
        .map(normalize_yn)
        .astype("boolean")
    )

    # --------------------------------------------------
    # 11. 취급품목
    # --------------------------------------------------

    out["item_tokens"] = (
        w["item_raw"]
        .map(parse_item_tokens)
    )

    out["item_text"] = (
        out["item_tokens"]
        .map(
            lambda xs:
            ", ".join(xs)
            if xs
            else None
        )
    )

    out["has_item"] = (
        out["item_tokens"]
        .map(bool)
    )

    out[
        "item_ambiguous_suffix"
    ] = (
        w["item_raw"]
        .map(has_ambiguous_suffix)
    )

    # taxonomy는 아직 만들지 않음
    out["item_normalized"] = pd.NA
    out["item_category_l1"] = pd.NA
    out["item_category_l2"] = pd.NA

    # --------------------------------------------------
    # 12. entity fingerprint
    #
    # 이 값은 중복 판단용.
    # PK(store_id)가 아니다.
    # --------------------------------------------------

    out[
        "entity_fingerprint"
    ] = [
        build_entity_fingerprint(
            business_no,
            store_name,
            address,
        )
        for (
            business_no,
            store_name,
            address,
        )
        in zip(
            out["business_no"],
            out["store_name"],
            out["address"],
        )
    ]

    return out


def find_duplicate_candidates(
    df: pd.DataFrame,
) -> pd.DataFrame:

    # 같은 store_id
    same_store_id = (
        df["store_id"]
        .duplicated(
            keep=False
        )
    )

    # 같은 사업자번호
    valid_business = (
        df["business_no"]
        .notna()
    )

    same_business_no = (
        valid_business
        & df[
            "business_no"
        ].duplicated(
            keep=False
        )
    )

    mask = (
        same_store_id
        | same_business_no
    )

    columns = [
        "store_id",
        "entity_fingerprint",
        "store_name",
        "business_no",
        "merchant_no",
        "address",
        "latitude",
        "longitude",
        "market_type",
        "market_name",
        "item_raw",
        "source_region",
        "source_sheet",
        "source_row_no",
        "source_record_key",
        "source_file",
    ]

    return (
        df.loc[
            mask,
            columns,
        ]
        .sort_values(
            [
                "business_no",
                "store_name",
            ],
            na_position="last",
        )
    )