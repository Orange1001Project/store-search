"""candidate pool 전체를 실제 relevance 판정용 애노테이션 시트로 바꾸는 로직.

scripts/08_make_full_annotation_sheets.py의 CLI 배관(인자 파싱, 콘솔 출력)을 제외한 핵심
로직 전체 — pool/queries 정합성 검사, query 메타데이터 부착, judgment_id 부여, annotator
A(train+val+test)/B(val+test) 시트 조립, split 통계, manifest 생성까지
(docs/PIPELINE_CODE_REFERENCE.md `08_make_full_annotation_sheets.py` 절 참고).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pandas as pd

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

QUERY_META_COLUMNS = ["query", "intent_definition", "split", "query_family", "query_type"]


def build_judgment_id(query_id: str, doc_id: str) -> str:
    """query-document pair의 영구 judgment ID.

    annotation 파일 순서가 달라져도 동일 query_id + doc_id라면 같은 judgment_id를 사용한다.
    """

    key = f"{query_id}|{doc_id}".encode()
    return hashlib.sha256(key).hexdigest()[:20]


def stable_shuffle(frame: pd.DataFrame, seed: int, annotator: str) -> pd.DataFrame:
    """Query는 묶어서 유지하되, query 내부 candidate 순서를 annotator별로 다르게 섞는다.

    A/B가 같은 순서에 노출되어 생길 수 있는 순서 효과를 줄이기 위한 deterministic shuffle.
    """

    x = frame.copy()
    x["_shuffle_key"] = x.apply(
        lambda row: hashlib.sha256(
            f"{seed}|{annotator}|{row['query_id']}|{row['doc_id']}".encode()
        ).hexdigest(),
        axis=1,
    )
    x = x.sort_values(["query_id", "_shuffle_key"])
    return x.drop(columns=["_shuffle_key"])


def write_annotation_file(frame: pd.DataFrame, output_path: Path) -> None:
    frame[VISIBLE_COLUMNS].to_csv(output_path, index=False, encoding="utf-8-sig")


# ============================================================
# Pool preparation
# ============================================================

def validate_pool_and_queries(pool: pd.DataFrame, queries: pd.DataFrame) -> None:
    """queries(active)/pool 정합성 검사: split 구성, query_id 중복, pool (query_id,doc_id) 중복,
    active query가 전부 pool에 후보를 갖고 있는지.
    """

    expected_splits = {"train", "val", "test"}
    actual_splits = set(queries["split"].unique())
    if actual_splits != expected_splits:
        raise ValueError(f"Expected train/val/test splits, but found: {sorted(actual_splits)}")

    if queries["query_id"].duplicated().any():
        raise ValueError("Duplicate query_id exists.")

    if pool.duplicated(["query_id", "doc_id"]).any():
        raise ValueError("Duplicate query_id/doc_id exists in candidate pool.")

    active_query_ids = set(queries["query_id"].astype(str))
    pool_query_ids = set(pool["query_id"].astype(str))
    missing_query_ids = active_query_ids - pool_query_ids
    if missing_query_ids:
        raise ValueError(f"Active queries without candidates: {sorted(missing_query_ids)[:20]}")


def attach_query_metadata(pool: pd.DataFrame, queries: pd.DataFrame) -> pd.DataFrame:
    """candidate_pool_internal.csv 안의 query text보다 현재 queries.csv를 authoritative source로
    써서 query/intent_definition/split/query_family/query_type을 붙이고, active query만 남긴다.
    """

    active_query_ids = set(queries["query_id"].astype(str))
    query_meta = queries.set_index("query_id").to_dict("index")

    pool = pool[pool["query_id"].isin(active_query_ids)].copy()
    for column in QUERY_META_COLUMNS:
        pool[column] = pool["query_id"].map(lambda qid, column=column: query_meta[qid][column])
    return pool


def add_judgment_ids(pool: pd.DataFrame) -> pd.DataFrame:
    pool = pool.copy()
    pool["judgment_id"] = [
        build_judgment_id(str(query_id), str(doc_id))
        for query_id, doc_id in zip(pool["query_id"], pool["doc_id"])
    ]
    if pool["judgment_id"].duplicated().any():
        raise ValueError("Duplicate judgment_id detected.")
    return pool


def add_empty_annotation_fields(pool: pd.DataFrame, round_name: str) -> pd.DataFrame:
    pool = pool.copy()
    pool["annotation_round"] = round_name
    pool["relevance"] = ""
    pool["uncertain"] = ""
    pool["annotator_note"] = ""
    return pool


def prepare_pool(pool: pd.DataFrame, queries: pd.DataFrame, round_name: str) -> pd.DataFrame:
    """검증 + 메타데이터 부착 + judgment_id 부여 + 빈 애노테이션 필드 추가를 한 번에 수행한다."""

    validate_pool_and_queries(pool, queries)
    pool = attach_query_metadata(pool, queries)
    pool = add_judgment_ids(pool)
    pool = add_empty_annotation_fields(pool, round_name)
    return pool


# ============================================================
# Annotator sheets
# ============================================================

def build_annotator_frame(
    pool: pd.DataFrame, seed: int, annotator: str, splits: list[str] | None = None
) -> pd.DataFrame:
    """annotator 컬럼을 채우고(splits가 주어지면 그 split만 남긴 뒤) stable_shuffle한다.

    A(전체 split)는 splits=None, B(val+test만)는 splits=["val","test"]로 호출한다.
    """

    frame = pool if splits is None else pool[pool["split"].isin(splits)]
    frame = frame.copy()
    frame["annotator"] = annotator
    return stable_shuffle(frame, seed, annotator)


# ============================================================
# Statistics / manifest
# ============================================================

def build_split_stats(pool: pd.DataFrame, splits: tuple[str, ...] = ("train", "val", "test")) -> list[dict]:
    stats = []
    for split in splits:
        split_pool = pool[pool["split"] == split]
        per_query = split_pool.groupby("query_id").size()
        stats.append(
            {
                "split": split,
                "queries": int(split_pool["query_id"].nunique()),
                "judgments": len(split_pool),
                "mean_candidates_per_query": float(per_query.mean()),
                "min_candidates_per_query": int(per_query.min()),
                "max_candidates_per_query": int(per_query.max()),
            }
        )
    return stats


def build_annotation_manifest(
    round_name: str,
    queries: pd.DataFrame,
    annotator_a: pd.DataFrame,
    annotator_b: pd.DataFrame,
    split_stats: list[dict],
) -> dict:
    return {
        "annotation_round": round_name,
        "benchmark_status": "PROVISIONAL",
        "purpose": (
            "Human-judged benchmark for zero-shot embedding model selection and subsequent "
            "small-scale fine-tuning experiments."
        ),
        "query_splits": {
            "train": int((queries["split"] == "train").sum()),
            "val": int((queries["split"] == "val").sum()),
            "test": int((queries["split"] == "test").sum()),
        },
        "annotator_A": {
            "splits": ["train", "val", "test"],
            "queries": int(annotator_a["query_id"].nunique()),
            "rows": len(annotator_a),
        },
        "annotator_B": {
            "splits": ["val", "test"],
            "queries": int(annotator_b["query_id"].nunique()),
            "rows": len(annotator_b),
        },
        "split_stats": split_stats,
        "relevance": {
            "grades": [0, 1, 2, 3],
            "binary_relevance_threshold": 2,
        },
        "annotation_policy": {
            "train": "Single human annotation. Used only for training/fine-tuning.",
            "validation": "Independent double human annotation followed by adjudication.",
            "test": "Independent double human annotation followed by adjudication.",
        },
        "data_leakage_policy": {
            "train": "May be used for fine-tuning, hard-negative mining, and training.",
            "validation": (
                "May be used for model/template/hyperparameter selection, but never gradient training."
            ),
            "test": (
                "Strictly held out. Must never be used for model training, hard-negative mining, "
                "prompt tuning, template selection, or hyperparameter selection."
            ),
        },
        "important": (
            "This is a provisional benchmark intended for embedding model selection and initial "
            "fine-tuning experiments. Publication-final benchmark freezing may require additional "
            "dense pooling and construct-validity review."
        ),
    }
