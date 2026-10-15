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


def test_notebook_pool_runs_cover_val_and_test_without_scoring(ns, tmp_path):
    import yaml

    ns.update(yaml=yaml, RUNS=tmp_path / "runs", MODEL_PRESETS={},
              queries=pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"], "split": ["val", "test"]}))
    exec(compile(_cell("pool"), "<notebook:pool>", "exec"), ns)  # noqa: S102 — 목록이 비어 있으면 정의만 한다
    ns["POOL_DEPTH"] = 2
    ns["make_pool_run"]({"name": "m", "model_id": "x"}, model=_FakeModel())

    run = pd.read_csv(tmp_path / "runs" / "pooling_runs" / "m.csv", encoding="utf-8-sig")
    assert set(run["query_id"]) == {"q1", "q2"}              # val + test 둘 다
    assert run.groupby("query_id")["rank"].max().eq(2).all() and set(run["system"]) == {"m"}
    assert run[run["rank"] == 1].set_index("query_id")["doc_id"].to_dict() == {"q1": "d1", "q2": "d2"}
    assert not (tmp_path / "runs" / "evaluation").exists()  # 채점 결과는 만들지 않음


def test_notebook_rescore_updates_drive_evaluations_after_qrels_change(ns, tmp_path):
    ns["evaluate"]({"name": "base", "model_id": "x"}, model=_FakeModel())
    ns["evaluate"]({"name": "ft", "model_id": "y"}, baseline_tag="base", model=_FakeModel(flip=True))
    ns["FINAL_TEST"] = False
    exec(compile(_cell("rescore"), "<notebook:rescore>", "exec"), ns)  # noqa: S102
    assert ns["rescore_evaluations"]() == 0                      # qrels가 그대로면 아무것도 안 바뀜

    qrels = tmp_path / "data" / "qrels_val.trec"
    qrels.write_text("q1 0 d3 3\nq1 0 d1 1\nq2 0 d2 3\nq2 0 d1 1\n", encoding="utf-8")   # 보충 판정으로 정답이 바뀐 경우
    assert ns["rescore_evaluations"]() == 2
    path = tmp_path / "runs" / "evaluation" / "ft_t1_minimal_val_evaluation.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    expected, _ = build_evaluation_report(qrels_path=qrels, run_path=Path(report["run"]), tag=report["tag"],
                                          bootstrap_samples=200, seed=7)
    assert report["aggregate"] == pytest.approx(expected["aggregate"])
    assert report["model_id"] == "y" and "previous_aggregate" in report["rescored"]
    assert report["comparison"]["baseline_tag"] == "base"


def test_notebook_typo_augmentation_is_deterministic_and_keeps_labels(ns):
    records = [
        {"query_id": "a", "query": "치킨 먹을 곳", "positives": [f"p{i}" for i in range(20)], "negatives": ["n1", "n2", "n3"]},
        {"query_id": "b", "query": "떡", "positives": ["p"], "negatives": ["n4", "n5", "n6"]},
    ]
    augmented = ns["augment_typo_records"](records, 3, 8, seed=7)
    assert augmented == ns["augment_typo_records"](records, 3, 8, seed=7)          # 다시 돌려도 같음
    by_source = {}
    for r in augmented:
        by_source.setdefault(r["augmented_from"], []).append(r)
    assert len(by_source["치킨 먹을 곳"]) == 3                                      # 요청한 개수만큼
    for source, variants in by_source.items():
        original = next(x for x in records if x["query"] == source)
        assert len({v["query"] for v in variants}) == len(variants)                # 서로 다른 변형
        for v in variants:
            assert v["query"] != source and v["query"].strip()
            assert v["positives"] == original["positives"][:8] and v["negatives"] == original["negatives"]

    rows, stats = ns["expand_training_rows"](records + augmented, 3, None)
    base_rows, _ = ns["expand_training_rows"](records, 3, None)
    assert rows[: len(base_rows)] == base_rows                                     # 원래 행은 그대로, 뒤에 덧붙음
    assert stats["n_queries_used"] == len(records) + len(augmented)


def test_notebook_make_typo_produces_korean_typos(ns):
    rng = np.random.default_rng(0)
    variants = {ns["make_typo"]("수산물", rng) for _ in range(300)} - {None}
    assert "수산물" not in variants and len(variants) > 20
    assert any(v.endswith(("추천", "근처", "어디")) for v in variants)            # 접미어
    assert any(len(v) == 3 and v[:2] == "수산" and v != "수산물" for v in variants)  # 마지막 음절 변형(받침·자모)
    assert any(v[0] != "수" for v in variants if len(v) == 3)                       # 첫 음절도 바뀜(마지막 글자만이 아님)


def test_notebook_service_metrics_counts_bad_top3(ns, tmp_path):
    exec(compile(_cell("board").split("\nboard = leaderboard(")[0], "<notebook:board>", "exec"), ns)  # noqa: S102
    ns["queries"] = pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"], "split": ["val", "val"],
                                  "query_type": ["T1 정확표기", "T6 기계변형"]})
    run = tmp_path / "run.csv"
    pd.DataFrame({"query_id": ["q1"] * 3 + ["q2"] * 3, "doc_id": ["d1", "d3", "d2", "d2", "d9", "d1"],
                  "rank": [1, 2, 3, 1, 2, 3], "score": [3, 2, 1, 3, 2, 1], "system": "m"}).to_csv(run, index=False)
    out = ns["service_metrics"](run, tmp_path / "data" / "qrels_val.trec")
    # q1: d3(rel 1)·d2(판정 없음)가 상위 3개에 있어 bad, 1위 d1(3) 정답. q2: d9(판정 없음) → bad, 1위 d2(3) 정답
    assert out["bad@3"] == 1.0 and out["top1_ok"] == 1.0
    assert out["bad@3 T1"] == 1.0 and out["bad@3 T6"] == 1.0


def test_notebook_typo_never_drops_first_syllable_of_a_word(ns):
    rng = np.random.default_rng(1)
    for _ in range(500):
        v = ns["make_typo"]("떡케이크", rng)
        assert v is None or v.startswith("떡") or v[0] != "케"   # 첫 음절을 지워 '케이크'가 되지 않음


def test_notebook_service_metrics_ignores_queries_without_qrels(ns, tmp_path):
    exec(compile(_cell("board").split("\nboard = leaderboard(")[0], "<notebook:board>", "exec"), ns)  # noqa: S102
    ns["queries"] = pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"], "split": ["val", "val"],
                                  "query_type": ["T1 정확표기", "T2 동의어"]})
    run = tmp_path / "run.csv"
    pd.DataFrame({"query_id": ["q1"] * 3 + ["q_typo"] * 3, "doc_id": ["d1", "d3", "d2", "d9", "d9", "d9"],
                  "rank": [1, 2, 3, 1, 2, 3], "score": [3, 2, 1, 3, 2, 1], "system": "m"}).to_csv(run, index=False)
    out = ns["service_metrics"](run, tmp_path / "data" / "qrels_val.trec")
    assert out["top1_ok"] == 1.0 and out["bad@3"] == 1.0          # q_typo(비활성, qrels 없음)는 세지 않음


def test_notebook_service_metrics_condensed_ndcg_ignores_unjudged_docs(ns, tmp_path):
    exec(compile(_cell("board").split("\nboard = leaderboard(")[0], "<notebook:board>", "exec"), ns)  # noqa: S102
    ns["queries"] = pd.DataFrame({"query_id": ["q1", "q2"], "query": ["치킨", "빵"], "split": ["val", "val"],
                                  "query_type": ["T1 정확표기", "T2 동의어"]})
    with_unjudged, judged_only = tmp_path / "a.csv", tmp_path / "b.csv"
    rows = [("q1", "x9", 1), ("q1", "d1", 2), ("q1", "d3", 3), ("q2", "d2", 1), ("q2", "x8", 2), ("q2", "d1", 3)]
    pd.DataFrame([{"query_id": q, "doc_id": d, "rank": r, "score": 10 - r, "system": "m"} for q, d, r in rows]).to_csv(
        with_unjudged, index=False)
    pd.DataFrame([{"query_id": q, "doc_id": d, "rank": r, "score": 10 - r, "system": "m"} for q, d, r in rows
                  if not d.startswith("x")]).to_csv(judged_only, index=False)
    a = ns["service_metrics"](with_unjudged, tmp_path / "data" / "qrels_val.trec")
    b = ns["service_metrics"](judged_only, tmp_path / "data" / "qrels_val.trec")
    assert a["nDCG@10(판정만)"] == pytest.approx(b["nDCG@10(판정만)"])   # 판정 없는 문서는 빼고 매김


def test_notebook_rescore_drops_rows_of_queries_without_qrels(ns, tmp_path):
    ns["evaluate"]({"name": "base", "model_id": "x"}, model=_FakeModel())
    run = tmp_path / "runs" / "model_eval" / "base" / "run_t1_minimal_val.csv"
    text = run.read_text(encoding="utf-8-sig")
    run.write_text(text + "q_typo,d1,1,0.9,base_t1_minimal\n", encoding="utf-8-sig")   # 비활성화 전에 만든 run 흉내
    (tmp_path / "data" / "qrels_val.trec").write_text("q1 0 d3 3\nq1 0 d1 1\nq2 0 d2 3\nq2 0 d1 1\n", encoding="utf-8")
    ns["FINAL_TEST"] = False
    exec(compile(_cell("rescore"), "<notebook:rescore>", "exec"), ns)  # noqa: S102
    assert "q_typo" not in run.read_text(encoding="utf-8-sig") and run.read_text(encoding="utf-8-sig") == text
    report = json.loads((tmp_path / "runs" / "evaluation" / "base_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    assert report["rescored"]["inactive_queries_dropped_from_runs"] == {"base": 1}
    assert report["run_validation"]["unknown_queries"] == 0 and len(report["rescored"]["qrels_sha256"]) == 64
