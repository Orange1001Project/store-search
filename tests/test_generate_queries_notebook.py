"""colab/generate_queries.ipynb의 프롬프트·파싱 셀(`# @cell prompts`)을 그대로 실행해 확인한다."""

import json
from pathlib import Path

import pandas as pd
import pytest

NOTEBOOK = Path(__file__).resolve().parents[1] / "colab" / "generate_queries.ipynb"


@pytest.fixture(scope="module")
def ns():
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    source = next("".join(c["source"]) for c in cells
                  if c["cell_type"] == "code" and "".join(c["source"]).startswith("# @cell prompts"))
    namespace: dict = {}
    exec(compile(source, "<notebook:prompts>", "exec"), namespace)  # noqa: S102
    return namespace


def test_parse_queries_reads_json_and_filters(ns):
    raw = '설명입니다\n["고기 파는 곳", "삼겹살", "삼겹살", "형제정육", "' + "가" * 40 + '", "x"]'
    assert ns["parse_queries"](raw, "형제정육 본점") == ["고기 파는 곳", "삼겹살"]


def test_parse_queries_falls_back_to_lines_and_strips_think(ns):
    raw = "<think>음</think>\n1. 반찬 가게\n- \"밑반찬 살 데\"\n"
    assert ns["parse_queries"](raw, "엄마손") == ["반찬 가게", "밑반찬 살 데"]


def test_build_messages_is_deterministic_per_store(ns):
    fewshot = pd.DataFrame(
        [{"bundle": "A", "family": f"f{i}", "type": "T2 동의어", "query": f"q{i}"} for i in range(10)]
    )
    a = ns["pick_examples"](fewshot, "A", "doc-1")
    assert a == ns["pick_examples"](fewshot, "A", "doc-1")
    assert len(a) == 6
    store = {"store_name": "형제정육", "item_text": "", "market_type": "전통시장"}
    user = ns["build_messages"]("C", store, a, 3)[1]["content"]
    assert "(없음)" in user and "3개" in user
