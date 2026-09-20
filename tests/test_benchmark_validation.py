import json

import pandas as pd

from store_search_ai.data.benchmark_validation import (
    build_base_report,
    build_validation_report,
    validate_corpus_integrity,
    validate_final_stage,
    validate_pool,
    validate_qrels,
    validate_query_integrity,
)


def _queries():
    return pd.DataFrame(
        [
            {"query_id": "q1", "query": "치킨", "query_family": "치킨", "split": "train"},
            {"query_id": "q2", "query": "빵", "query_family": "빵", "split": "val"},
        ]
    )


def _corpus():
    return pd.DataFrame({"doc_id": ["d1", "d2"]})


def _config(**overrides):
    cfg = {
        "relevance": {"grades": [0, 1, 2, 3], "binary_threshold": 2},
        "validation": {
            "min_relevant_per_query": 1,
            "min_total_queries_final": 1,
            "min_test_queries_final": 0,
            "target_double_annotation_coverage": 1.0,
        },
        "pooling": {"min_pool_size_warn": 1, "min_pool_systems_final": 1},
    }
    cfg.update(overrides)
    return cfg


def test_validate_query_integrity_detects_duplicate_query_id():
    queries = pd.concat([_queries(), _queries().iloc[[0]]], ignore_index=True)
    errors = validate_query_integrity(queries)
    assert "Duplicate query_id exists" in errors


def test_validate_query_integrity_detects_duplicate_normalized_text():
    # normalization casefolds and collapses internal whitespace runs (doesn't strip ends)
    queries = _queries()
    queries.loc[0, "query"] = "Chicken  Place"
    queries.loc[1, "query"] = "chicken place"
    errors = validate_query_integrity(queries)
    assert "Duplicate normalized query text exists" in errors


def test_validate_query_integrity_detects_family_split_leakage():
    queries = _queries()
    queries.loc[1, "query_family"] = "치킨"  # same family, different split as row 0
    errors = validate_query_integrity(queries)
    assert any("leakage" in e for e in errors)


def test_validate_query_integrity_passes_clean_queries():
    assert validate_query_integrity(_queries()) == []


def test_validate_corpus_integrity_detects_duplicate_doc_id():
    corpus = pd.concat([_corpus(), _corpus().iloc[[0]]], ignore_index=True)
    assert "Corpus doc_id is not unique" in validate_corpus_integrity(corpus)


def test_build_base_report_schema():
    report = build_base_report("pilot", _queries(), _corpus())
    assert report == {
        "stage": "pilot", "queries": 2, "query_families": 2,
        "queries_by_split": {"train": 1, "val": 1}, "corpus_docs": 2,
    }


def test_validate_pool_detects_unknown_doc_id_and_warns_small_pool():
    pool = pd.DataFrame(
        [
            {"query_id": "q1", "doc_id": "d_unknown", "pool_sources_json": json.dumps({"run:sysA": {}})},
        ]
    )
    config = _config(pooling={"min_pool_size_warn": 5, "min_pool_systems_final": 1})
    updates, errors, warnings = validate_pool(pool, _corpus(), config)
    assert any("unknown doc_ids" in e for e in errors)
    assert updates["pool_systems"] == ["sysA"]
    assert any("smaller than" in w for w in warnings)


def test_validate_qrels_detects_invalid_grade_and_unknown_ids():
    qrels = pd.DataFrame(
        [{"query_id": "q_unknown", "doc_id": "d_unknown", "relevance": 9}]
    )
    _updates, errors = validate_qrels(qrels, _queries(), _corpus(), _config())
    assert "Invalid qrels grade" in errors
    assert "Unknown query_id in qrels" in errors
    assert "Unknown doc_id in qrels" in errors


def test_validate_qrels_detects_missing_and_zero_relevant_queries():
    qrels = pd.DataFrame([{"query_id": "q1", "doc_id": "d1", "relevance": 0}])
    _updates, errors = validate_qrels(qrels, _queries(), _corpus(), _config())
    assert any("no judgments" in e for e in errors)  # q2 missing
    assert any("no relevance>=2" in e for e in errors)  # q1 has only relevance=0


def test_validate_final_stage_flags_missing_agreement():
    report = {"pool_system_count": 3}
    errors = validate_final_stage(report, _queries(), _config())
    assert "Missing human agreement report" in errors


def test_validate_final_stage_flags_incomplete_double_annotation():
    report = {"pool_system_count": 3, "agreement": {"double_annotation_coverage": 0.5}}
    errors = validate_final_stage(report, _queries(), _config())
    assert "Incomplete val/test double annotation" in errors


def test_build_validation_report_pilot_valid_true_when_no_errors():
    report = build_validation_report(_config(), "pilot", _queries(), _corpus())
    assert report["valid"] is True
    assert report["errors"] == []


def test_build_validation_report_final_without_agreement_is_invalid():
    report = build_validation_report(_config(), "final", _queries(), _corpus())
    assert report["valid"] is False
    assert "Missing human agreement report" in report["errors"]
