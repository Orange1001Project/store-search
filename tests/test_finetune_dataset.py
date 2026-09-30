
import pandas as pd
import pytest

from store_search_ai.data.finetune_dataset import (
    build_training_pairs,
    resolve_train_qrels_path,
)


def _queries():
    return pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"]}).set_index("query_id")


def _doc_text():
    return pd.Series(
        {"d1": "치킨집", "d2": "생닭", "d3": "빵집", "d4": "케이크집", "d5": "떡집"}
    )


def test_build_training_pairs_selects_positive_and_negatives():
    qrels = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d2", "relevance": 1},
        ]
    )
    records, stats = build_training_pairs(qrels, _queries(), _doc_text(), threshold=2, max_negatives=8)
    assert len(records) == 1
    assert records[0]["query_id"] == "q1"
    assert records[0]["positives"] == ["치킨집"]
    assert records[0]["negatives"] == ["생닭"]
    assert stats == {
        "n_written": 1,
        "n_skipped_no_positive": 0,
        "total_positives": 1,
        "total_negatives": 1,
    }


def test_build_training_pairs_skips_queries_with_no_positive():
    qrels = pd.DataFrame(
        [{"query_id": "q1", "doc_id": "d2", "relevance": 1}]
    )
    records, stats = build_training_pairs(qrels, _queries(), _doc_text(), threshold=2, max_negatives=8)
    assert records == []
    assert stats["n_skipped_no_positive"] == 1


def test_build_training_pairs_prioritizes_harder_negatives_first():
    qrels = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d2", "relevance": 0},
            {"query_id": "q1", "doc_id": "d3", "relevance": 1},
        ]
    )
    records, _ = build_training_pairs(qrels, _queries(), _doc_text(), threshold=2, max_negatives=8)
    # relevance=1 (d3) should come before relevance=0 (d2)
    assert records[0]["negatives"] == ["빵집", "생닭"]


def test_build_training_pairs_respects_max_negatives_limit():
    qrels = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d2", "relevance": 0},
            {"query_id": "q1", "doc_id": "d3", "relevance": 0},
            {"query_id": "q1", "doc_id": "d4", "relevance": 0},
        ]
    )
    records, stats = build_training_pairs(qrels, _queries(), _doc_text(), threshold=2, max_negatives=2)
    assert len(records[0]["negatives"]) == 2
    assert stats["total_negatives"] == 2


def test_build_training_pairs_keeps_all_positives_highest_relevance_first():
    qrels = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d3", "relevance": 2},
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d4", "relevance": 2},
        ]
    )
    records, stats = build_training_pairs(qrels, _queries(), _doc_text(), threshold=2, max_negatives=8)
    # relevance=3이 먼저, 같은 relevance 안에서는 qrels 순서 유지
    assert records[0]["positives"] == ["치킨집", "빵집", "케이크집"]
    assert stats["total_positives"] == 3


def test_build_training_pairs_dedupes_identical_texts_and_drops_them_from_negatives():
    doc_text = pd.Series({"d1": "치킨집", "d2": "치킨집", "d3": "치킨집", "d4": "생닭", "d5": "생닭"})
    qrels = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d1", "relevance": 3},
            {"query_id": "q1", "doc_id": "d2", "relevance": 2},
            {"query_id": "q1", "doc_id": "d3", "relevance": 1},  # 정답과 텍스트가 같음 -> negative 제외
            {"query_id": "q1", "doc_id": "d4", "relevance": 0},
            {"query_id": "q1", "doc_id": "d5", "relevance": 0},
        ]
    )
    records, _ = build_training_pairs(qrels, _queries(), doc_text, threshold=2, max_negatives=8)
    assert records[0]["positives"] == ["치킨집"]
    assert records[0]["negatives"] == ["생닭"]


def test_resolve_train_qrels_path_prefers_final_over_provisional(tmp_path):
    (tmp_path / "qrels_train.csv").write_text("data", encoding="utf-8")
    provisional_dir = tmp_path / "qrels" / "full_annotation_v1"
    provisional_dir.mkdir(parents=True)
    (provisional_dir / "qrels_train_provisional.csv").write_text("data", encoding="utf-8")

    assert resolve_train_qrels_path(tmp_path, "full_annotation_v1") == tmp_path / "qrels_train.csv"


def test_resolve_train_qrels_path_falls_back_to_provisional(tmp_path):
    provisional_dir = tmp_path / "qrels" / "full_annotation_v1"
    provisional_dir.mkdir(parents=True)
    (provisional_dir / "qrels_train_provisional.csv").write_text("data", encoding="utf-8")

    assert (
        resolve_train_qrels_path(tmp_path, "full_annotation_v1")
        == provisional_dir / "qrels_train_provisional.csv"
    )


def test_resolve_train_qrels_path_raises_when_neither_exists(tmp_path):
    with pytest.raises(SystemExit, match="train qrels를 찾을 수 없습니다"):
        resolve_train_qrels_path(tmp_path, "full_annotation_v1")
