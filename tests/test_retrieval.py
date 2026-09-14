from __future__ import annotations

import numpy as np

from store_search_ai.models.random_encoder import RandomEncoder
from store_search_ai.retrieval.exact_search import ExactCosineSearch


def test_random_encoder_is_deterministic_per_text():
    encoder = RandomEncoder(dim=16)
    a = encoder.encode_corpus(["가맹점명: 열매서점 / 취급품목: 서적"])
    b = encoder.encode_corpus(["가맹점명: 열매서점 / 취급품목: 서적"])
    assert np.allclose(a, b)


def test_exact_cosine_search_returns_expected_schema_and_rank_order():
    # doc0과 정확히 같은 벡터를 query로 주면, doc0이 항상 rank=1이어야 한다.
    corpus_embeddings = np.array(
        [
            [1.0, 0.0],
            [0.0, 1.0],
            [0.7071, 0.7071],
        ],
        dtype="float32",
    )
    doc_ids = ["doc_a", "doc_b", "doc_c"]
    searcher = ExactCosineSearch(corpus_embeddings, doc_ids)

    query_embeddings = np.array([[1.0, 0.0]], dtype="float32")
    run = searcher.search(
        query_embeddings=query_embeddings,
        query_ids=["q1"],
        top_k=2,
        system="unit_test",
    )

    assert list(run.columns) == ["query_id", "doc_id", "rank", "score", "system"]
    assert len(run) == 2  # top_k=2
    top1 = run[run["rank"] == 1].iloc[0]
    assert top1["doc_id"] == "doc_a"
    assert top1["query_id"] == "q1"
    assert top1["system"] == "unit_test"


def test_exact_cosine_search_rejects_mismatched_doc_id_count():
    corpus_embeddings = np.zeros((3, 4), dtype="float32")
    try:
        ExactCosineSearch(corpus_embeddings, doc_ids=["only_one"])
        assert False, "should have raised ValueError"
    except ValueError:
        pass
