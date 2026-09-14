from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config, sha256_file, write_trec_qrels


VALID_SPLITS = {"train", "val", "test"}
VALID_GRADES = {0, 1, 2, 3}
TRUE_VALUES = {"Y", "YES", "TRUE", "1"}


def truthy(value: object) -> bool:
    if value is None or pd.isna(value):
        return False

    return (
        str(value)
        .strip()
        .upper()
        in TRUE_VALUES
    )


def write_trec(
    frame: pd.DataFrame,
    path: Path,
) -> None:
    required = {
        "query_id",
        "doc_id",
        "relevance",
    }

    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"TREC input missing columns: {sorted(missing)}"
        )

    write_trec_qrels(frame, path)


def validate_qrels(
    qrels: pd.DataFrame,
    split: str,
) -> None:

    required = {
        "query_id",
        "doc_id",
        "relevance",
    }

    missing = required - set(qrels.columns)

    if missing:
        raise ValueError(
            f"{split}: missing columns: {sorted(missing)}"
        )

    if qrels.empty:
        raise ValueError(
            f"{split}: qrels is empty."
        )

    if qrels[
        ["query_id", "doc_id"]
    ].duplicated().any():

        raise ValueError(
            f"{split}: duplicate query_id/doc_id pair."
        )

    relevance = pd.to_numeric(
        qrels["relevance"],
        errors="coerce",
    )

    if relevance.isna().any():

        raise ValueError(
            f"{split}: missing or invalid relevance."
        )

    invalid = set(
        relevance.astype(int).unique()
    ) - VALID_GRADES

    if invalid:

        raise ValueError(
            f"{split}: invalid relevance values: "
            f"{sorted(invalid)}"
        )


def build_split_qrels(
    adj: pd.DataFrame,
    split: str,
) -> pd.DataFrame:

    frame = adj[
        adj["split"].astype(str) == split
    ].copy()

    frame["exclude"] = (
        frame["exclude_from_gold"]
        .map(truthy)
    )

    frame["final_rel_num"] = pd.to_numeric(
        frame["final_relevance"],
        errors="coerce",
    )

    unresolved = frame[
        ~frame["exclude"]
        & frame["final_rel_num"].isna()
    ]

    if len(unresolved):

        raise ValueError(
            f"{split}: "
            f"{len(unresolved)} unresolved "
            "non-excluded rows."
        )

    valid = frame[
        ~frame["exclude"]
    ].copy()

    valid["relevance"] = (
        valid["final_rel_num"]
        .astype(int)
    )

    columns = [
        "query_id",
        "doc_id",
        "relevance",
        "query_family",
    ]

    qrels = valid[columns].copy()

    validate_qrels(
        qrels,
        split,
    )

    return qrels


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
        "--adjudication",
        default=(
            "benchmark/storesearch_ko_v1/"
            "annotations/full_annotation_v1/"
            "analysis/"
            "adjudication_val_test_full_completed.csv"
        ),
    )

    parser.add_argument(
        "--train-qrels",
        default=(
            "benchmark/storesearch_ko_v1/"
            "qrels/provisional_v1/"
            "qrels_train_provisional.csv"
        ),
    )

    parser.add_argument(
        "--freeze",
        action="store_true",
    )

    args = parser.parse_args()

    # --------------------------------------------------
    # 1. Load configuration
    # --------------------------------------------------

    config_path = Path(args.config)

    config = load_config(config_path)

    benchmark_dir = Path(
        config["benchmark_dir"]
    )

    benchmark_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------
    # 2. Load queries
    # --------------------------------------------------

    queries_path = (
        benchmark_dir
        / "queries.csv"
    )

    queries = pd.read_csv(
        queries_path,
        encoding="utf-8-sig",
    )

    active_queries = queries[
        queries["status"]
        .astype(str)
        .str.lower()
        .eq("active")
    ].copy()

    active_query_ids = set(
        active_queries[
            "query_id"
        ].astype(str)
    )

    # --------------------------------------------------
    # 3. Load completed adjudication
    # --------------------------------------------------

    adjudication_path = Path(
        args.adjudication
    )

    if not adjudication_path.exists():

        raise FileNotFoundError(
            "Adjudication file not found: "
            f"{adjudication_path}"
        )

    adj = pd.read_csv(
        adjudication_path,
        encoding="utf-8-sig",
    )

    required_adj = {
        "query_id",
        "doc_id",
        "split",
        "query_family",
        "final_relevance",
        "exclude_from_gold",
    }

    missing_adj = (
        required_adj
        - set(adj.columns)
    )

    if missing_adj:

        raise ValueError(
            "Adjudication file missing "
            f"columns: {sorted(missing_adj)}"
        )

    # --------------------------------------------------
    # 4. Build validation/test qrels
    # --------------------------------------------------

    qrels_val = build_split_qrels(
        adj,
        "val",
    )

    qrels_test = build_split_qrels(
        adj,
        "test",
    )

    # --------------------------------------------------
    # 5. Load train qrels
    # --------------------------------------------------

    train_path = Path(
        args.train_qrels
    )

    if not train_path.exists():

        raise FileNotFoundError(
            "Train qrels not found: "
            f"{train_path}"
        )

    qrels_train = pd.read_csv(
        train_path,
        encoding="utf-8-sig",
    )

    # 기존 provisional 파일에는
    # query_family가 포함되어 있어야 한다.
    if "query_family" not in qrels_train.columns:

        raise ValueError(
            "Train qrels must contain "
            "query_family."
        )

    validate_qrels(
        qrels_train,
        "train",
    )

    # --------------------------------------------------
    # 6. Validate query IDs
    # --------------------------------------------------

    for split, qrels in [
        ("train", qrels_train),
        ("val", qrels_val),
        ("test", qrels_test),
    ]:

        unknown_queries = (
            set(
                qrels["query_id"]
                .astype(str)
            )
            - active_query_ids
        )

        if unknown_queries:

            raise ValueError(
                f"{split}: "
                f"{len(unknown_queries)} "
                "query_ids are not present "
                "in active queries.csv."
            )

    # --------------------------------------------------
    # 7. Add split explicitly
    # --------------------------------------------------

    qrels_train = (
        qrels_train.copy()
    )
    qrels_train["split"] = "train"

    qrels_val = (
        qrels_val.copy()
    )
    qrels_val["split"] = "val"

    qrels_test = (
        qrels_test.copy()
    )
    qrels_test["split"] = "test"

    # --------------------------------------------------
    # 8. Build all qrels
    # --------------------------------------------------

    qrels_all = pd.concat(
        [
            qrels_train,
            qrels_val,
            qrels_test,
        ],
        ignore_index=True,
    )

    if qrels_all[
        ["query_id", "doc_id"]
    ].duplicated().any():

        raise ValueError(
            "Duplicate query_id/doc_id "
            "across splits."
        )

    # --------------------------------------------------
    # 9. Save final CSV artifacts
    # --------------------------------------------------

    output_frames = {
        "train": qrels_train,
        "val": qrels_val,
        "test": qrels_test,
        "all": qrels_all,
    }

    csv_paths = {}

    for name, frame in output_frames.items():

        path = (
            benchmark_dir
            / f"qrels_{name}.csv"
            if name != "all"
            else benchmark_dir
            / "qrels.csv"
        )

        frame.to_csv(
            path,
            index=False,
            encoding="utf-8-sig",
        )

        csv_paths[name] = path

    # --------------------------------------------------
    # 10. Save final TREC artifacts
    # --------------------------------------------------

    trec_frames = {
        "train": qrels_train,
        "val": qrels_val,
        "test": qrels_test,
        "all": qrels_all,
    }

    trec_paths = {}

    for name, frame in trec_frames.items():

        path = (
            benchmark_dir
            / f"qrels_{name}.trec"
            if name != "all"
            else benchmark_dir
            / "qrels.trec"
        )

        write_trec(
            frame[
                [
                    "query_id",
                    "doc_id",
                    "relevance",
                ]
            ],
            path,
        )

        trec_paths[name] = path

    # --------------------------------------------------
    # 11. Statistics
    # --------------------------------------------------

    def split_summary(
        frame: pd.DataFrame,
    ) -> dict:

        return {
            "queries": int(
                frame["query_id"]
                .nunique()
            ),
            "judgments": int(
                len(frame)
            ),
            "grade_distribution": {
                str(int(k)): int(v)
                for k, v in (
                    frame["relevance"]
                    .value_counts()
                    .sort_index()
                    .items()
                )
            },
            "binary_relevant_ge_2": int(
                (
                    frame["relevance"]
                    >= 2
                ).sum()
            ),
        }

    # --------------------------------------------------
    # 12. Manifest
    # --------------------------------------------------

    manifest = {

        "benchmark_version":
            config["benchmark_version"],

        "dataset_version":
            config["dataset_version"],

        "corpus_version":
            config["corpus_version"],

        "benchmark_status":
            "PROVISIONAL",

        "binary_relevance_threshold":
            2,

        "document_representation":
            "T1: store_name + item_text",

        "query_count":
            int(
                active_queries[
                    "query_id"
                ].nunique()
            ),

        "splits": {

            "train":
                split_summary(
                    qrels_train
                ),

            "val":
                split_summary(
                    qrels_val
                ),

            "test":
                split_summary(
                    qrels_test
                ),

            "all":
                split_summary(
                    qrels_all
                ),
        },

        "files": {
            "queries.csv":
                sha256_file(
                    queries_path
                ),

            "qrels_train.csv":
                sha256_file(
                    csv_paths["train"]
                ),

            "qrels_val.csv":
                sha256_file(
                    csv_paths["val"]
                ),

            "qrels_test.csv":
                sha256_file(
                    csv_paths["test"]
                ),

            "qrels.csv":
                sha256_file(
                    csv_paths["all"]
                ),

            "qrels_train.trec":
                sha256_file(
                    trec_paths["train"]
                ),

            "qrels_val.trec":
                sha256_file(
                    trec_paths["val"]
                ),

            "qrels_test.trec":
                sha256_file(
                    trec_paths["test"]
                ),

            "qrels.trec":
                sha256_file(
                    trec_paths["all"]
                ),
        },

        "source": {

            "adjudication":
                str(
                    adjudication_path
                ),

            "train_qrels":
                str(
                    train_path
                ),
        },

        "important": (
            "Train is used for model "
            "fine-tuning. Val is used for "
            "checkpoint, template and "
            "hyperparameter selection. "
            "Test remains held out until "
            "the final configuration is fixed."
        ),
    }

    manifest_path = (
        benchmark_dir
        / "benchmark_manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------
    # 13. Optional immutable freeze
    # --------------------------------------------------

    if args.freeze:

        frozen = (
            benchmark_dir
            / "frozen"
        )

        if frozen.exists():

            raise FileExistsError(
                f"{frozen} already exists. "
                "Never overwrite a frozen benchmark."
            )

        frozen.mkdir(
            parents=True
        )

        files_to_freeze = [
            queries_path,
            benchmark_dir
            / "annotation_guideline.md",

            csv_paths["train"],
            csv_paths["val"],
            csv_paths["test"],
            csv_paths["all"],

            trec_paths["train"],
            trec_paths["val"],
            trec_paths["test"],
            trec_paths["all"],

            manifest_path,
            config_path,
        ]

        for src in files_to_freeze:

            if src.exists():

                shutil.copy2(
                    src,
                    frozen / src.name,
                )

        print(
            f"[FROZEN] {frozen}"
        )

    # --------------------------------------------------
    # 14. Print result
    # --------------------------------------------------

    print()
    print(
        "========== FINAL QRELS BUILT =========="
    )
    print()

    print(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()