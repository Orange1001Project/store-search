from __future__ import annotations

import argparse
import hashlib
import json

from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config


def text_hash(
    value: object,
) -> str | None:
    """
    검색 text가 바뀌었는지 추적하기 위한 SHA256.
    나중에 incremental embedding에서 사용.
    """

    if value is None or pd.isna(value):
        return None

    text = str(value)

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default="configs/benchmark/storesearch_ko_v1.yaml",
        help="dataset_version/corpus_version을 읽어올 benchmark config",
    )

    parser.add_argument(
        "--input",
        default=None,
        help="기본값: data/processed/stores_master_{dataset_version}.parquet",
    )

    parser.add_argument(
        "--output",
        default=None,
        help="기본값: data/corpus/{corpus_version}.parquet",
    )

    parser.add_argument(
        "--manifest",
        default=None,
        help="기본값: data/corpus/{corpus_version}_manifest.json",
    )

    args = parser.parse_args()

    config = load_config(args.config)

    DATASET_VERSION = config["dataset_version"]
    CORPUS_VERSION = config["corpus_version"]

    if args.input is None:
        args.input = f"data/processed/stores_master_{DATASET_VERSION}.parquet"

    if args.output is None:
        args.output = f"data/corpus/{CORPUS_VERSION}.parquet"

    if args.manifest is None:
        args.manifest = f"data/corpus/{CORPUS_VERSION}_manifest.json"

    input_path = Path(
        args.input
    )

    output_path = Path(
        args.output
    )

    manifest_path = Path(
        args.manifest
    )

    df = pd.read_parquet(
        input_path
    )

    # --------------------------------------------------
    # 필수 조건 검사
    # --------------------------------------------------

    if df["store_id"].isna().any():

        raise ValueError(
            "store_id NULL이 존재합니다."
        )

    if df["store_id"].duplicated().any():

        raise ValueError(
            "store_id 중복이 존재합니다."
        )

    # --------------------------------------------------
    # Corpus schema
    # --------------------------------------------------

    columns = [
        "store_id",
        "store_name",

        "market_name",
        "market_type",

        "item_text",
        "has_item",

        "address",
        "latitude",
        "longitude",
        "geo_status",
        "legal_dong_code",

        "source_region",

        "card_payment",
        "mobile_payment",

        "search_text_t1_minimal",
        "search_text_t2_market",
        "search_text_t3_market_type",
    ]

    corpus = (
        df[
            columns
        ]
        .copy()
    )

    # Benchmark / retrieval에서 명칭을 명확히 하기 위해
    # document ID도 별도로 제공
    corpus.insert(
        0,
        "doc_id",
        corpus["store_id"],
    )

    corpus[
        "dataset_version"
    ] = DATASET_VERSION

    corpus[
        "corpus_version"
    ] = CORPUS_VERSION

    # --------------------------------------------------
    # 각 template별 hash
    #
    # 향후:
    # text가 안 바뀐 매장은 재임베딩하지 않을 수 있음.
    # --------------------------------------------------

    corpus[
        "content_hash_t1"
    ] = (
        corpus[
            "search_text_t1_minimal"
        ]
        .map(text_hash)
    )

    corpus[
        "content_hash_t2"
    ] = (
        corpus[
            "search_text_t2_market"
        ]
        .map(text_hash)
    )

    corpus[
        "content_hash_t3"
    ] = (
        corpus[
            "search_text_t3_market_type"
        ]
        .map(text_hash)
    )

    # --------------------------------------------------
    # 저장
    # --------------------------------------------------

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    corpus.to_parquet(
        output_path,
        index=False,
    )

    # --------------------------------------------------
    # Manifest
    # --------------------------------------------------

    manifest = {

        "corpus_version":
            CORPUS_VERSION,

        "dataset_version":
            DATASET_VERSION,

        "source_dataset":
            str(
                input_path
            ),

        "documents":
            int(
                len(corpus)
            ),

        "unique_doc_ids":
            int(
                corpus[
                    "doc_id"
                ]
                .nunique()
            ),

        "missing_item_documents":
            int(
                (
                    ~corpus[
                        "has_item"
                    ]
                )
                .sum()
            ),

        "geo_missing_documents":
            int(
                (
                    corpus[
                        "geo_status"
                    ]
                    != "VALID"
                )
                .sum()
            ),

        "templates": {

            "t1_minimal":
                "가맹점명 + 취급품목",

            "t2_market":
                "가맹점명 + 시장명 + 취급품목",

            "t3_market_type":
                (
                    "가맹점명 + 시장명 "
                    "+ 시장유형 + 취급품목"
                ),
        },

        "primary_template":
            None,
    }

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()

    print(
        "========== "
        "CORPUS V001 COMPLETE "
        "=========="
    )

    print()

    print(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
    )

    print()

    print(
        corpus[
            [
                "doc_id",
                "search_text_t1_minimal",
                "search_text_t2_market",
                "search_text_t3_market_type",
            ]
        ]
        .head(10)
        .to_string(
            index=False
        )
    )


if __name__ == "__main__":
    main()