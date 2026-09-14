from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config


VISIBLE_COLUMNS = [
    "judgment_id",
    "annotation_round",
    "annotator",
    "query_id",
    "query",
    "intent_definition",
    "split",
    "query_family",
    "query_type",
    "doc_id",
    "store_name",
    "item_text",
    "market_name",
    "market_type",
    "source_region",
    "relevance",
    "uncertain",
    "annotator_note",
]


def build_judgment_id(
    query_id: str,
    doc_id: str,
) -> str:
    """
    query-document pair의 영구 judgment ID.

    annotation 파일 순서가 달라져도
    동일 query_id + doc_id라면 같은 judgment_id를 사용한다.
    """

    key = f"{query_id}|{doc_id}".encode("utf-8")

    return hashlib.sha256(
        key
    ).hexdigest()[:20]


def stable_shuffle(
    frame: pd.DataFrame,
    seed: int,
    annotator: str,
) -> pd.DataFrame:
    """
    Query는 묶어서 유지하되,
    Query 내부 candidate 순서를 annotator별로 다르게 섞는다.

    A/B가 같은 순서에 노출되어 생길 수 있는
    순서 효과를 줄이기 위한 deterministic shuffle.
    """

    x = frame.copy()

    x["_shuffle_key"] = x.apply(
        lambda row: hashlib.sha256(
            (
                f"{seed}|"
                f"{annotator}|"
                f"{row['query_id']}|"
                f"{row['doc_id']}"
            ).encode("utf-8")
        ).hexdigest(),
        axis=1,
    )

    x = x.sort_values(
        [
            "query_id",
            "_shuffle_key",
        ]
    )

    return x.drop(
        columns=[
            "_shuffle_key",
        ]
    )


def write_annotation_file(
    frame: pd.DataFrame,
    output_path: Path,
) -> None:

    frame[
        VISIBLE_COLUMNS
    ].to_csv(
        output_path,
        index=False,
        encoding="utf-8-sig",
    )


def main() -> None:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--config",
        default=(
            "configs/benchmark/"
            "storesearch_ko_v1.yaml"
        ),
    )

    parser.add_argument(
        "--round",
        default="full_annotation_v1",
    )

    args = parser.parse_args()

    # ==================================================
    # Config
    # ==================================================

    config_path = Path(
        args.config
    )

    config = load_config(config_path)

    benchmark_dir = Path(
        config[
            "benchmark_dir"
        ]
    )

    # ==================================================
    # Load
    # ==================================================

    pool_path = (
        benchmark_dir
        / "candidate_pool_internal.csv"
    )

    queries_path = (
        benchmark_dir
        / "queries.csv"
    )

    pool = pd.read_csv(
        pool_path
    )

    queries = pd.read_csv(
        queries_path
    )

    queries = queries[
        queries["status"]
        == "active"
    ].copy()

    # ==================================================
    # Integrity checks
    # ==================================================

    expected_splits = {
        "train",
        "val",
        "test",
    }

    actual_splits = set(
        queries[
            "split"
        ].unique()
    )

    if actual_splits != expected_splits:

        raise ValueError(
            "Expected train/val/test splits, "
            f"but found: {sorted(actual_splits)}"
        )

    if queries[
        "query_id"
    ].duplicated().any():

        raise ValueError(
            "Duplicate query_id exists."
        )

    if pool.duplicated(
        [
            "query_id",
            "doc_id",
        ]
    ).any():

        raise ValueError(
            "Duplicate query_id/doc_id exists "
            "in candidate pool."
        )

    active_query_ids = set(
        queries[
            "query_id"
        ].astype(str)
    )

    pool_query_ids = set(
        pool[
            "query_id"
        ].astype(str)
    )

    missing_query_ids = (
        active_query_ids
        - pool_query_ids
    )

    if missing_query_ids:

        raise ValueError(
            "Active queries without candidates: "
            f"{sorted(missing_query_ids)[:20]}"
        )

    # ==================================================
    # Query metadata
    #
    # candidate_pool_internal.csv 안의 query text보다
    # 현재 queries.csv를 authoritative source로 사용한다.
    # ==================================================

    query_meta = (
        queries
        .set_index(
            "query_id"
        )
        .to_dict(
            "index"
        )
    )

    pool = pool[
        pool[
            "query_id"
        ].isin(
            active_query_ids
        )
    ].copy()

    pool["query"] = pool[
        "query_id"
    ].map(
        lambda qid:
        query_meta[
            qid
        ][
            "query"
        ]
    )

    pool["intent_definition"] = pool[
        "query_id"
    ].map(
        lambda qid:
        query_meta[
            qid
        ][
            "intent_definition"
        ]
    )

    pool["split"] = pool[
        "query_id"
    ].map(
        lambda qid:
        query_meta[
            qid
        ][
            "split"
        ]
    )

    pool["query_family"] = pool[
        "query_id"
    ].map(
        lambda qid:
        query_meta[
            qid
        ][
            "query_family"
        ]
    )

    pool["query_type"] = pool[
        "query_id"
    ].map(
        lambda qid:
        query_meta[
            qid
        ][
            "query_type"
        ]
    )

    # ==================================================
    # Stable judgment_id
    # ==================================================

    pool["judgment_id"] = [
        build_judgment_id(
            str(query_id),
            str(doc_id),
        )
        for query_id, doc_id
        in zip(
            pool[
                "query_id"
            ],
            pool[
                "doc_id"
            ],
        )
    ]

    if pool[
        "judgment_id"
    ].duplicated().any():

        raise ValueError(
            "Duplicate judgment_id detected."
        )

    # ==================================================
    # Empty annotation fields
    # ==================================================

    pool[
        "annotation_round"
    ] = args.round

    pool[
        "relevance"
    ] = ""

    pool[
        "uncertain"
    ] = ""

    pool[
        "annotator_note"
    ] = ""

    seed = int(
        config[
            "annotation"
        ][
            "random_seed"
        ]
    )

    # ==================================================
    # Output
    # ==================================================

    output_dir = (
        benchmark_dir
        / "annotations"
        / "full_annotation_v1"
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ==================================================
    # Human A
    #
    # Train + Val + Test 전체 판정
    #
    # Train:
    #   fine-tuning dataset 생성
    #
    # Val:
    #   hyperparameter / template / model selection
    #
    # Test:
    #   final held-out evaluation
    # ==================================================

    a = pool.copy()

    a[
        "annotator"
    ] = "A"

    a = stable_shuffle(
        a,
        seed,
        "A",
    )

    write_annotation_file(
        a,
        output_dir
        / "annotation_A_all.csv",
    )

    # 편하게 작업할 수 있도록 split별 파일도 생성.
    for split in [
        "train",
        "val",
        "test",
    ]:

        split_a = a[
            a[
                "split"
            ]
            == split
        ].copy()

        write_annotation_file(
            split_a,
            output_dir
            / f"annotation_A_{split}.csv",
        )

    # ==================================================
    # Human B
    #
    # Validation + Test를 독립적으로 재판정.
    #
    # Train은 training signal이므로
    # 모델 성능 보고용 gold가 아니기 때문에
    # 시간 절약을 위해 single annotation.
    # ==================================================

    b = pool[
        pool[
            "split"
        ].isin(
            [
                "val",
                "test",
            ]
        )
    ].copy()

    b[
        "annotator"
    ] = "B"

    b = stable_shuffle(
        b,
        seed,
        "B",
    )

    write_annotation_file(
        b,
        output_dir
        / "annotation_B_val_test.csv",
    )

    for split in [
        "val",
        "test",
    ]:

        split_b = b[
            b[
                "split"
            ]
            == split
        ].copy()

        write_annotation_file(
            split_b,
            output_dir
            / f"annotation_B_{split}.csv",
        )

    # ==================================================
    # Split statistics
    # ==================================================

    split_stats = []

    for split in [
        "train",
        "val",
        "test",
    ]:

        split_pool = pool[
            pool[
                "split"
            ]
            == split
        ]

        split_stats.append(
            {
                "split":
                    split,

                "queries":
                    int(
                        split_pool[
                            "query_id"
                        ].nunique()
                    ),

                "judgments":
                    int(
                        len(
                            split_pool
                        )
                    ),

                "mean_candidates_per_query":
                    float(
                        split_pool
                        .groupby(
                            "query_id"
                        )
                        .size()
                        .mean()
                    ),

                "min_candidates_per_query":
                    int(
                        split_pool
                        .groupby(
                            "query_id"
                        )
                        .size()
                        .min()
                    ),

                "max_candidates_per_query":
                    int(
                        split_pool
                        .groupby(
                            "query_id"
                        )
                        .size()
                        .max()
                    ),
            }
        )

    # ==================================================
    # Manifest
    # ==================================================

    manifest = {

        "annotation_round":
            args.round,

        "benchmark_status":
            "PROVISIONAL",

        "purpose":
            (
                "Human-judged benchmark for "
                "zero-shot embedding model selection "
                "and subsequent small-scale "
                "fine-tuning experiments."
            ),

        "query_splits": {
            "train":
                int(
                    (
                        queries[
                            "split"
                        ]
                        == "train"
                    ).sum()
                ),

            "val":
                int(
                    (
                        queries[
                            "split"
                        ]
                        == "val"
                    ).sum()
                ),

            "test":
                int(
                    (
                        queries[
                            "split"
                        ]
                        == "test"
                    ).sum()
                ),
        },

        "annotator_A": {
            "splits": [
                "train",
                "val",
                "test",
            ],

            "queries":
                int(
                    a[
                        "query_id"
                    ].nunique()
                ),

            "rows":
                int(
                    len(
                        a
                    )
                ),
        },

        "annotator_B": {
            "splits": [
                "val",
                "test",
            ],

            "queries":
                int(
                    b[
                        "query_id"
                    ].nunique()
                ),

            "rows":
                int(
                    len(
                        b
                    )
                ),
        },

        "split_stats":
            split_stats,

        "relevance": {
            "grades": [
                0,
                1,
                2,
                3,
            ],

            "binary_relevance_threshold":
                2,
        },

        "annotation_policy": {

            "train":
                (
                    "Single human annotation. "
                    "Used only for training/fine-tuning."
                ),

            "validation":
                (
                    "Independent double human annotation "
                    "followed by adjudication."
                ),

            "test":
                (
                    "Independent double human annotation "
                    "followed by adjudication."
                ),
        },

        "data_leakage_policy": {

            "train":
                (
                    "May be used for fine-tuning, "
                    "hard-negative mining, and training."
                ),

            "validation":
                (
                    "May be used for model/template/"
                    "hyperparameter selection, "
                    "but never gradient training."
                ),

            "test":
                (
                    "Strictly held out. "
                    "Must never be used for model training, "
                    "hard-negative mining, prompt tuning, "
                    "template selection, or hyperparameter selection."
                ),
        },

        "important": (
            "This is a provisional benchmark intended "
            "for embedding model selection and initial "
            "fine-tuning experiments. "
            "Publication-final benchmark freezing may "
            "require additional dense pooling and "
            "construct-validity review."
        ),
    }

    manifest_path = (
        output_dir
        / "annotation_manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # ==================================================
    # Print
    # ==================================================

    print()

    print(
        "========== "
        "FULL ANNOTATION SHEETS CREATED "
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
        "IMPORTANT:"
    )

    print(
        "- Train: A only"
    )

    print(
        "- Val: A + B independent"
    )

    print(
        "- Test: A + B independent"
    )

    print(
        "- Never use Test for training or hard-negative mining."
    )


if __name__ == "__main__":
    main()