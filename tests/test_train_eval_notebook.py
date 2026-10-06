"""colab/train_eval.ipynb 안의 코드가 저장소의 공식 구현과 어긋나지 않는지 확인한다.

노트북은 Colab에서 `src/` 없이 혼자 돌도록 학습·채점 코드를 직접 담고 있다(팀원이 셀에서 기법을 바로 고칠 수 있게).
그래서 이 테스트가 노트북의 셀을 그대로 실행해서
- 채점 결과(지표·신뢰구간·기준 대비 비교)가 공식 evaluator(`build_evaluation_report`)와 **같은지**
- 학습 행 펼치기가 `store_search_ai.training.finetune.expand_training_rows`와 같은지
- run 정리·태그 규칙이 기존 규칙과 같은지
를 본다. 노트북의 "7. 평가" 셀을 고쳐서 채점이 달라지면 여기서 실패한다.
"""

import contextlib
import gc
import json
import re
import types
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from store_search_ai.evaluation.evaluator import build_evaluation_report
from store_search_ai.training.finetune import expand_training_rows as reference_expand

NOTEBOOK = Path(__file__).resolve().parents[1] / "colab" / "train_eval.ipynb"


def _cell(tag: str) -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for cell in cells:
        source = "".join(cell["source"])
        if cell["cell_type"] == "code" and source.startswith(f"# @cell {tag}"):
            return source
    raise AssertionError(f"노트북에 '# @cell {tag}' 셀이 없습니다")


@pytest.fixture
def ns(tmp_path):
    """노트북 셀을 실행할 이름 공간(Colab에서 앞 셀들이 만들어 두는 전역 값들을 흉내 낸다)."""

    fake_torch = types.SimpleNamespace(
        no_grad=contextlib.nullcontext,
        cuda=types.SimpleNamespace(is_available=lambda: False, empty_cache=lambda: None),
    )
    namespace = {"Path": Path, "pd": pd, "np": np, "json": json, "re": re, "gc": gc, "datetime": datetime,
                 "UTC": UTC, "torch": fake_torch}
    for tag in ("compat", "rows", "runs", "eval"):
        # 노트북 셀 코드를 그대로 실행하는 것이 이 테스트의 목적(저장소 안의 노트북 파일만 실행)
        exec(compile(_cell(tag), f"<notebook:{tag}>", "exec"), namespace)  # noqa: S102

    data = tmp_path / "data"
    data.mkdir()
    (data / "qrels_val.trec").write_text("q1 0 d1 3\nq1 0 d3 1\nq2 0 d2 3\nq2 0 d1 1\n", encoding="utf-8")
    runs = tmp_path / "runs"
    namespace.update(
        RUN_DIR=runs / "model_eval", EVAL_DIR=runs / "evaluation", FINETUNE_DIR=runs / "finetune", OFFICIAL=True,
        QRELS={"val": data / "qrels_val.trec"}, EVAL_SETTINGS={"bootstrap_samples": 200, "random_seed": 7},
        corpus=pd.DataFrame({"doc_id": ["d1", "d2", "d3"], "search_text_t1_minimal": ["치킨집", "빵집", "떡집"]}),
        queries=pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"], "split": ["val", "val"]}),
    )
    return namespace


VECTORS = {"치킨집": [1.0, 0.0], "빵집": [0.0, 1.0], "떡집": [0.7, 0.7], "치킨": [1.0, 0.1], "빵": [0.2, 1.0]}


class _FakeModel:

    def __init__(self, flip=False):
        self.flip = flip

    def encode(self, texts, **kwargs):
        vectors = np.array([VECTORS[t] for t in texts], dtype="float32")
        is_doc = "prompt" not in kwargs and "prompt_name" not in kwargs and texts[0].endswith("집")
        return vectors[:, ::-1].copy() if (self.flip and is_doc) else vectors


def test_notebook_scoring_matches_official_evaluator(ns, tmp_path):
    good = ns["evaluate"]({"name": "good", "model_id": "x"}, model=_FakeModel())
    bad = ns["evaluate"]({"name": "bad", "model_id": "x"}, model=_FakeModel(flip=True), baseline_tag="good")

    for result, baseline in ((good, None), (bad, ns["RUN_DIR"] / "good" / "run_t1_minimal_val.csv")):
        notebook_report = result["report"]
        official, _ = build_evaluation_report(
            qrels_path=ns["QRELS"]["val"], run_path=result["run_path"], tag=notebook_report["tag"],
            bootstrap_samples=200, seed=7, compare_run_path=baseline, compare_tag="good",
        )
        assert notebook_report["aggregate"] == pytest.approx(official["aggregate"])
        assert notebook_report["query_bootstrap_ci95"] == official["query_bootstrap_ci95"]
        assert notebook_report["run_validation"] == official["run_validation"]
        if baseline is not None:
            assert notebook_report["comparison"]["metrics"] == official["comparison"]["metrics"]

    assert bad["report"]["aggregate"]["nDCG@10"] < good["report"]["aggregate"]["nDCG@10"]
    saved = json.loads((ns["EVAL_DIR"] / "bad_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    assert saved["official"] is True and saved["comparison"]["baseline_tag"] == "good"
    board = ns["leaderboard"]("val")
    assert board["tag"].tolist() == ["good_t1_minimal_val", "bad_t1_minimal_val"]


def test_notebook_blocks_test_split_and_records_manifest(ns, tmp_path):
    with pytest.raises(ValueError, match="allow_test"):
        ns["evaluate"]({"name": "m", "model_id": "x"}, split="test", model=_FakeModel())

    model_dir = tmp_path / "ft"
    model_dir.mkdir()
    (model_dir / "model_manifest.json").write_text(json.dumps({"evaluations": []}), encoding="utf-8")
    ns["evaluate"]({"name": "ft", "model_id": str(model_dir)}, model=_FakeModel())
    manifest = json.loads((model_dir / "model_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluations"][0]["tag"] == "ft_t1_minimal_val"


def test_notebook_row_expansion_matches_reference(ns):
    records = [
        {"query_id": "a", "query": "치킨", "positives": ["p1", "p2", "p3"], "negatives": ["n1", "n2", "n3", "n4"]},
        {"query_id": "b", "query": "빵", "positives": ["p4"], "negatives": ["n5"]},
        {"query_id": "c", "query": "떡", "positive": "p5", "negatives": ["n6", "n7", "n8"]},
    ]
    for k, cap in ((3, 2), (1, None), (0, 1)):
        assert ns["expand_training_rows"](records, k, cap) == reference_expand(records, k, cap)


def test_notebook_run_management_rules(ns, tmp_path):
    now = datetime(2026, 10, 6, 1, 2, tzinfo=UTC)
    assert ns["make_run_tag"]("bge_m3", "jisu", now) == "bge_m3_ft_jisu_20261006_0102"

    root = tmp_path / "finetune"
    root.mkdir()
    for i, keep in ((1, False), (2, True), (3, False), (4, False)):
        run = root / f"bge_m3_ft_jisu_2026100{i}_0000"
        run.mkdir()
        (run / "model_manifest.json").write_text(json.dumps({"created_at": f"2026-10-0{i}"}), encoding="utf-8")
        if keep:
            (run / "KEEP").write_text("", encoding="utf-8")
    other = root / "bge_m3_ft_minho_20261001_0000"
    other.mkdir()
    (other / "model_manifest.json").write_text(json.dumps({"created_at": "2026-10-01"}), encoding="utf-8")

    ns["prune_runs"](root, ns["run_prefix"]("bge_m3", "jisu"), keep_last=2)
    assert sorted(p.name for p in root.iterdir()) == [
        "bge_m3_ft_jisu_20261002_0000", "bge_m3_ft_jisu_20261003_0000", "bge_m3_ft_jisu_20261004_0000",
        "bge_m3_ft_minho_20261001_0000",
    ]
    assert ns["latest_checkpoint"](tmp_path / "missing") is None
