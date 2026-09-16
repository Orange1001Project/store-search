
import numpy as np
import pandas as pd

from store_search_ai.retrieval.lexical import (
    build_lexical_run_manifest,
    build_pool_document_texts,
    fit_bm25_scorer,
    fit_char_tfidf_scorer,
    fit_word_tfidf_scorer,
    normalize_text,
    retrieve_run,
    tokenize,
    write_run_files,
)


def test_normalize_text_collapses_whitespace_and_handles_none():
    assert normalize_text("  치킨   집  ") == "치킨 집"
    assert normalize_text(None) == ""
    assert normalize_text(float("nan")) == ""


def test_tokenize_extracts_alnum_hangul_tokens_casefolded():
    assert tokenize("Chicken 치킨-집!!") == ["chicken", "치킨", "집"]


def test_build_pool_document_texts_concatenates_store_name_and_item_text():
    corpus = pd.DataFrame({"store_name": ["치킨집", None], "item_text": ["치킨", "빵"]})
    docs = build_pool_document_texts(corpus)
    assert docs.iloc[0] == "치킨집 치킨"
    assert docs.iloc[1] == "빵"


def _corpus():
    return pd.DataFrame(
        {
            "doc_id": ["d1", "d2", "d3"],
            "store_name": ["치킨나라", "빵집나라", "카페나라"],
            "item_text": ["치킨 통닭", "빵 케이크", "커피 라떼"],
        }
    )


def _queries(query_texts):
    return pd.DataFrame({"query_id": [f"q{i}" for i in range(len(query_texts))], "query": query_texts})


def test_retrieve_run_excludes_zero_score_documents():
    corpus = _corpus()
    docs = build_pool_document_texts(corpus)
    score_fn = fit_bm25_scorer(docs)
    queries = _queries(["치킨", "존재하지않는단어xyz123"])

    run, stats = retrieve_run("bm25_regex_v1", queries, corpus, score_fn, top_k=10)

    assert set(run[run["query_id"] == "q0"]["doc_id"]) == {"d1"}
    assert "q1" not in set(run["query_id"])
    assert stats["queries_with_results"] == 1
    assert stats["queries_without_results"] == 1
    assert stats["run_rows"] == len(run)


def test_retrieve_run_respects_top_k_and_ranks_by_score_descending():
    corpus = pd.DataFrame(
        {"doc_id": ["d1", "d2", "d3"], "store_name": ["치킨", "치킨치킨", "치킨치킨치킨"], "item_text": ["", "", ""]}
    )
    docs = build_pool_document_texts(corpus)
    score_fn = fit_char_tfidf_scorer(docs)
    queries = _queries(["치킨"])

    run, _ = retrieve_run("char_tfidf_v1", queries, corpus, score_fn, top_k=2)
    assert len(run) == 2
    assert list(run["rank"]) == [1, 2]
    assert run["score"].is_monotonic_decreasing


def test_fit_scorers_are_deterministic_for_the_same_corpus():
    corpus = _corpus()
    docs = build_pool_document_texts(corpus)

    for fit in (fit_char_tfidf_scorer, fit_word_tfidf_scorer, fit_bm25_scorer):
        score_fn = fit(docs)
        first = np.asarray(score_fn("치킨"))
        second = np.asarray(score_fn("치킨"))
        assert np.array_equal(first, second)


def test_write_run_files_writes_csv_and_trec(tmp_path):
    run = pd.DataFrame(
        [{"query_id": "q1", "doc_id": "d1", "rank": 1, "score": 0.5, "system": "sys1"}]
    )
    csv_path, trec_path = write_run_files(run, "sys1", tmp_path)

    assert csv_path == tmp_path / "sys1.csv"
    assert trec_path == tmp_path / "sys1.trec"
    assert trec_path.read_text(encoding="utf-8").strip() == "q1 Q0 d1 1 0.500000000000 sys1"


def test_build_lexical_run_manifest_schema():
    manifest = build_lexical_run_manifest(40, ["a", "b"], [{"system": "a"}, {"system": "b"}])
    assert manifest["run_depth"] == 40
    assert manifest["systems"] == ["a", "b"]
    assert manifest["pool_text_fields"] == ["store_name", "item_text"]
    assert len(manifest["run_stats"]) == 2
