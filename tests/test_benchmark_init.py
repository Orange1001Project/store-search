import pytest

from store_search_ai.data.benchmark_init import (
    GUIDELINE,
    build_queries_frame,
    build_query_manifest,
)


def _query_cfg(**overrides):
    cfg = {
        "query_set_version": "query_set_test",
        "families": [
            {
                "family": "치킨",
                "split": "train",
                "intent_definition": "치킨 파는 곳",
                "positive_terms": ["치킨", "통닭"],
                "boundary_terms": ["생닭"],
                "queries": [
                    {"type": "T1 정확표기", "text": "치킨"},
                    {"type": "T2 동의어", "text": "통닭"},
                ],
            }
        ],
    }
    cfg.update(overrides)
    return cfg


def test_build_queries_frame_assigns_sequential_query_ids():
    frame = build_queries_frame(_query_cfg())
    assert list(frame["query_id"]) == ["q_치킨_01", "q_치킨_02"]
    assert list(frame["query"]) == ["치킨", "통닭"]
    assert (frame["status"] == "active").all()


def test_build_queries_frame_serializes_terms_pipe_delimited():
    frame = build_queries_frame(_query_cfg())
    assert frame.iloc[0]["pool_positive_terms"] == "치킨|통닭"
    assert frame.iloc[0]["pool_boundary_terms"] == "생닭"


def test_build_queries_frame_rejects_duplicate_family():
    families = _query_cfg()["families"]
    cfg = _query_cfg(families=families + families)
    with pytest.raises(ValueError, match="Duplicate family"):
        build_queries_frame(cfg)


def test_build_queries_frame_rejects_invalid_split():
    cfg = _query_cfg()
    cfg["families"][0]["split"] = "holdout"
    with pytest.raises(ValueError, match="Invalid split"):
        build_queries_frame(cfg)


def test_build_queries_frame_rejects_zero_query_variants():
    cfg = _query_cfg()
    cfg["families"][0]["queries"] = []
    with pytest.raises(ValueError, match="must have >=1"):
        build_queries_frame(cfg)


def test_build_queries_frame_rejects_duplicate_normalized_query_text():
    cfg = _query_cfg()
    cfg["families"][0]["queries"].append({"type": "T4", "text": " 통닭 "})
    with pytest.raises(ValueError, match="Duplicate query text"):
        build_queries_frame(cfg)


def test_build_queries_frame_defaults_missing_terms_to_empty():
    cfg = _query_cfg()
    del cfg["families"][0]["positive_terms"]
    del cfg["families"][0]["boundary_terms"]
    frame = build_queries_frame(cfg)
    assert frame.iloc[0]["pool_positive_terms"] == ""
    assert frame.iloc[0]["pool_boundary_terms"] == ""


def test_build_query_manifest_schema():
    cfg = _query_cfg()
    queries = build_queries_frame(cfg)
    manifest = build_query_manifest(
        config={"benchmark_version": "v1"}, query_cfg=cfg, queries=queries,
        queries_sha256="abc", families_config_sha256="def",
    )
    assert manifest["benchmark_version"] == "v1"
    assert manifest["query_set_version"] == "query_set_test"
    assert manifest["total_queries"] == 2
    assert manifest["families"] == 1
    assert manifest["queries_by_split"] == {"train": 2}
    assert manifest["families_by_split"] == {"train": 1}
    assert manifest["queries_sha256"] == "abc"
    assert manifest["families_config_sha256"] == "def"


def test_guideline_mentions_binary_threshold_and_blind_annotation():
    assert "relevance >= 2" in GUIDELINE
    assert "Blind annotation" in GUIDELINE


def test_build_queries_frame_marks_listed_queries_inactive_and_checks_text(tmp_path):
    from store_search_ai.data.benchmark_init import load_inactive_queries

    listed = tmp_path / "inactive.yaml"
    listed.write_text('inactive_queries:\n  - {query_id: q_치킨_02, query: "통닭", reason: typo}\n', encoding="utf-8")
    inactive = load_inactive_queries(listed)
    frame = build_queries_frame(_query_cfg(), inactive)
    assert dict(zip(frame["query_id"], frame["status"])) == {"q_치킨_01": "active", "q_치킨_02": "inactive"}
    assert load_inactive_queries(tmp_path / "missing.yaml") == {}

    with pytest.raises(ValueError, match="맞지 않습니다"):
        build_queries_frame(_query_cfg(), {"q_치킨_02": "치킨집"})      # 번호가 밀려 다른 쿼리를 가리키면 멈춤
    with pytest.raises(ValueError, match="맞지 않습니다"):
        build_queries_frame(_query_cfg(), {"q_치킨_09": "통닭"})

    manifest = build_query_manifest({"benchmark_version": "b"}, _query_cfg(), frame, "s", "f")
    assert (manifest["active_queries"], manifest["inactive_queries"]) == (1, 1)
    assert "inactive_queries" not in build_query_manifest({"benchmark_version": "b"}, _query_cfg(),
                                                          build_queries_frame(_query_cfg()), "s", "f")
