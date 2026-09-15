"""train(provisional) + val/test(adjudication 완료본)를 합쳐 최종 공식 qrels를 만드는 로직.

scripts/11_build_qrels.py의 CLI 배관(인자 파싱, 콘솔 출력)을 제외한 핵심 로직 전체 —
adjudication/provisional train qrels 로딩과 검증, split별 qrels 조립, 저장, 통계/매니페스트
생성, 동결(freeze)까지. 이 단계를 통과해야 비로소 "gold"라고 부를 수 있다
(docs/PIPELINE_CODE_REFERENCE.md `11_build_qrels.py` 절 참고).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import write_trec_qrels

VALID_SPLITS = {"train", "val", "test"}
VALID_GRADES = {0, 1, 2, 3}
TRUE_VALUES = {"Y", "YES", "TRUE", "1"}

REQUIRED_ADJUDICATION_COLUMNS = {
    "query_id", "doc_id", "split", "query_family", "final_relevance", "exclude_from_gold",
}


def truthy(value: object) -> bool:
    if value is None or pd.isna(value):
        return False
    return str(value).strip().upper() in TRUE_VALUES


def write_trec(frame: pd.DataFrame, path: Path) -> None:
    required = {"query_id", "doc_id", "relevance"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"TREC input missing columns: {sorted(missing)}")
    write_trec_qrels(frame, path)


def validate_qrels(qrels: pd.DataFrame, split: str) -> None:
    required = {"query_id", "doc_id", "relevance"}
    missing = required - set(qrels.columns)
    if missing:
        raise ValueError(f"{split}: missing columns: {sorted(missing)}")

    if qrels.empty:
        raise ValueError(f"{split}: qrels is empty.")

    if qrels[["query_id", "doc_id"]].duplicated().any():
        raise ValueError(f"{split}: duplicate query_id/doc_id pair.")

    relevance = pd.to_numeric(qrels["relevance"], errors="coerce")
    if relevance.isna().any():
        raise ValueError(f"{split}: missing or invalid relevance.")

    invalid = set(relevance.astype(int).unique()) - VALID_GRADES
    if invalid:
        raise ValueError(f"{split}: invalid relevance values: {sorted(invalid)}")


def build_split_qrels(adj: pd.DataFrame, split: str) -> pd.DataFrame:
    frame = adj[adj["split"].astype(str) == split].copy()
    frame["exclude"] = frame["exclude_from_gold"].map(truthy)
    frame["final_rel_num"] = pd.to_numeric(frame["final_relevance"], errors="coerce")

    unresolved = frame[~frame["exclude"] & frame["final_rel_num"].isna()]
    if len(unresolved):
        raise ValueError(f"{split}: {len(unresolved)} unresolved non-excluded rows.")

    valid = frame[~frame["exclude"]].copy()
    valid["relevance"] = valid["final_rel_num"].astype(int)

    qrels = valid[["query_id", "doc_id", "relevance", "query_family"]].copy()
    validate_qrels(qrels, split)
    return qrels


# ============================================================
# Loading
# ============================================================

def load_adjudication(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Adjudication file not found: {path}")

    adj = pd.read_csv(path, encoding="utf-8-sig")
    missing_adj = REQUIRED_ADJUDICATION_COLUMNS - set(adj.columns)
    if missing_adj:
        raise ValueError(f"Adjudication file missing columns: {sorted(missing_adj)}")
    return adj


def load_train_qrels(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Train qrels not found: {path}")

    qrels_train = pd.read_csv(path, encoding="utf-8-sig")
    # 기존 provisional 파일에는 query_family가 포함되어 있어야 한다.
    if "query_family" not in qrels_train.columns:
        raise ValueError("Train qrels must contain query_family.")

    validate_qrels(qrels_train, "train")
    return qrels_train


# ============================================================
# Assembly
# ============================================================

def assemble_qrels(
    qrels_train: pd.DataFrame,
    qrels_val: pd.DataFrame,
    qrels_test: pd.DataFrame,
    active_query_ids: set[str],
) -> dict[str, pd.DataFrame]:
    """train/val/test qrels에 split 컬럼을 붙이고, query_id 유효성 + 교차 split 중복을 검사한 뒤
    {"train", "val", "test", "all"} 4개 DataFrame을 반환한다.
    """

    for split, qrels in [("train", qrels_train), ("val", qrels_val), ("test", qrels_test)]:
        unknown_queries = set(qrels["query_id"].astype(str)) - active_query_ids
        if unknown_queries:
            raise ValueError(
                f"{split}: {len(unknown_queries)} query_ids are not present in active queries.csv."
            )

    qrels_train = qrels_train.copy()
    qrels_train["split"] = "train"
    qrels_val = qrels_val.copy()
    qrels_val["split"] = "val"
    qrels_test = qrels_test.copy()
    qrels_test["split"] = "test"

    qrels_all = pd.concat([qrels_train, qrels_val, qrels_test], ignore_index=True)
    if qrels_all[["query_id", "doc_id"]].duplicated().any():
        raise ValueError("Duplicate query_id/doc_id across splits.")

    return {"train": qrels_train, "val": qrels_val, "test": qrels_test, "all": qrels_all}


# ============================================================
# Saving
# ============================================================

def save_qrels_outputs(
    benchmark_dir: Path, qrels_frames: dict[str, pd.DataFrame]
) -> tuple[dict[str, Path], dict[str, Path]]:
    """qrels_{train,val,test}.csv/.trec + qrels.csv/.trec을 저장하고 (csv_paths, trec_paths)를 반환한다."""

    csv_paths: dict[str, Path] = {}
    for name, frame in qrels_frames.items():
        path = benchmark_dir / (f"qrels_{name}.csv" if name != "all" else "qrels.csv")
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        csv_paths[name] = path

    trec_paths: dict[str, Path] = {}
    for name, frame in qrels_frames.items():
        path = benchmark_dir / (f"qrels_{name}.trec" if name != "all" else "qrels.trec")
        write_trec(frame[["query_id", "doc_id", "relevance"]], path)
        trec_paths[name] = path

    return csv_paths, trec_paths


# ============================================================
# Statistics / manifest
# ============================================================

def split_summary(frame: pd.DataFrame) -> dict:
    return {
        "queries": int(frame["query_id"].nunique()),
        "judgments": len(frame),
        "grade_distribution": {
            str(int(k)): int(v) for k, v in frame["relevance"].value_counts().sort_index().items()
        },
        "binary_relevant_ge_2": int((frame["relevance"] >= 2).sum()),
    }


def build_manifest(
    config: dict,
    active_query_count: int,
    qrels_frames: dict[str, pd.DataFrame],
    queries_path: Path,
    csv_paths: dict[str, Path],
    trec_paths: dict[str, Path],
    adjudication_path: Path,
    train_path: Path,
    sha256_file,
) -> dict:
    """benchmark_manifest.json 스키마의 dict를 만든다.

    `sha256_file`을 인자로 받는 이유: 파일 해시라는 IO를 함수 시그니처에서 명시적으로 드러내
    (테스트에서 가짜 해셔로 교체하기 쉽게) 하기 위함 — store_search_ai.pipeline.common.sha256_file을
    그대로 넘기면 된다.
    """

    return {
        "benchmark_version": config["benchmark_version"],
        "dataset_version": config["dataset_version"],
        "corpus_version": config["corpus_version"],
        "benchmark_status": "PROVISIONAL",
        "binary_relevance_threshold": 2,
        "document_representation": "T1: store_name + item_text",
        "query_count": active_query_count,
        "splits": {name: split_summary(frame) for name, frame in qrels_frames.items()},
        "files": {
            "queries.csv": sha256_file(queries_path),
            "qrels_train.csv": sha256_file(csv_paths["train"]),
            "qrels_val.csv": sha256_file(csv_paths["val"]),
            "qrels_test.csv": sha256_file(csv_paths["test"]),
            "qrels.csv": sha256_file(csv_paths["all"]),
            "qrels_train.trec": sha256_file(trec_paths["train"]),
            "qrels_val.trec": sha256_file(trec_paths["val"]),
            "qrels_test.trec": sha256_file(trec_paths["test"]),
            "qrels.trec": sha256_file(trec_paths["all"]),
        },
        "source": {
            "adjudication": str(adjudication_path),
            "train_qrels": str(train_path),
        },
        "important": (
            "Train is used for model fine-tuning. Val is used for checkpoint, template and "
            "hyperparameter selection. Test remains held out until the final configuration is fixed."
        ),
    }


# ============================================================
# Freeze
# ============================================================

def freeze_benchmark(frozen_dir: Path, files_to_freeze: list[Path]) -> None:
    """benchmark_dir/frozen/에 산출물을 통째로 복사해 불변 스냅샷을 만든다.

    frozen_dir가 이미 있으면 거부한다(동결된 벤치마크를 실수로 덮어쓰지 못하게).
    """

    if frozen_dir.exists():
        raise FileExistsError(f"{frozen_dir} already exists. Never overwrite a frozen benchmark.")

    frozen_dir.mkdir(parents=True)
    for path in files_to_freeze:
        if path.exists():
            shutil.copy2(path, frozen_dir / path.name)


def manifest_json(manifest: dict) -> str:
    return json.dumps(manifest, ensure_ascii=False, indent=2)
