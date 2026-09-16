"""리팩터링 전후로 prepare_finetune_dataset.py의 산출물이 동일한지 확인하는 golden-file
회귀 테스트.

qrels_train.csv, queries.csv는 체크인돼 있고, data/corpus/*.parquet만 재생성 가능한 중간
산출물(SHARE_NOTES.md)이라 로컬에 없으면 스킵된다 - 02_preprocess_data.py + 04_build_corpus.py로
재생성하면 실행된다.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.finetune_dataset import TEMPLATE_COLUMNS, build_training_pairs
from store_search_ai.pipeline.common import load_active_queries, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "benchmark" / "storesearch_ko_v1.yaml"
GOLDEN_PATH = REPO_ROOT / "data" / "finetune" / "train_pairs.jsonl"


def _corpus_path() -> Path:
    config = load_config(CONFIG_PATH)
    return REPO_ROOT / config["corpus_path"]


pytestmark = pytest.mark.skipif(
    not _corpus_path().exists(),
    reason="data/corpus/*.parquet 없음 (재생성 가능한 중간 산출물 - 02+04로 재생성 후 다시 실행)",
)


def test_training_pairs_match_checked_in_golden_file(tmp_path):
    config = load_config(CONFIG_PATH)
    benchmark_dir = REPO_ROOT / config["benchmark_dir"]
    threshold = int(config["evaluation"]["binary_relevance_threshold"])

    qrels = pd.read_csv(benchmark_dir / "qrels_train.csv", encoding="utf-8-sig")
    queries = load_active_queries(benchmark_dir)
    queries = queries[queries["split"] == "train"].set_index("query_id")

    corpus = pd.read_parquet(REPO_ROOT / config["corpus_path"])
    doc_text = corpus.set_index("doc_id")[TEMPLATE_COLUMNS["t1_minimal"]].fillna("").astype(str)

    qrels = qrels[qrels["query_id"].isin(queries.index) & qrels["doc_id"].isin(doc_text.index)]

    records, _stats = build_training_pairs(qrels, queries, doc_text, threshold=threshold, max_negatives=8)

    written_path = tmp_path / "train_pairs.jsonl"
    with written_path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    assert written_path.read_bytes() == GOLDEN_PATH.read_bytes()
