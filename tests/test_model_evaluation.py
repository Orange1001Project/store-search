import json

import numpy as np
import pandas as pd
import pytest

from store_search_ai.evaluation.model_evaluation import (
    collect_leaderboard,
    evaluate_model,
    evaluation_tag,
    format_report,
)

VECTORS = {"치킨집": [1, 0], "빵집": [0, 1], "떡집": [0.7, 0.7], "치킨": [1, 0], "빵": [0, 1]}


class FakeEncoder:
    """문서/쿼리 텍스트를 미리 정한 2차원 벡터로 바꾸는 가짜 인코더(torch 없이 평가 파이프라인 검증용).
    flip=True면 문서 벡터만 뒤집어서 일부러 틀린 순위를 낸다."""

    def __init__(self, flip=False):
        self.config = {}
        self.flip = flip
        self.corpus_calls = 0

    def _encode(self, texts):
        return np.array([VECTORS[t] for t in texts], dtype="float32")

    def encode_corpus(self, texts):
        self.corpus_calls += 1
        vectors = self._encode(texts)
        return vectors[:, ::-1].copy() if self.flip else vectors

    def encode_queries(self, texts):
        return self._encode(texts)


@pytest.fixture
def inputs(tmp_path):
    benchmark_dir = tmp_path / "benchmark"
    benchmark_dir.mkdir()
    (benchmark_dir / "qrels_val.trec").write_text("q1 0 d1 3\nq1 0 d3 1\nq2 0 d2 3\n", encoding="utf-8")
    (benchmark_dir / "qrels_test.trec").write_text("q3 0 d1 3\n", encoding="utf-8")
    return {
        "config": {"evaluation": {"bootstrap_samples": 50, "random_seed": 1}},
        "corpus": pd.DataFrame({"doc_id": ["d1", "d2", "d3"], "search_text_t1_minimal": ["치킨집", "빵집", "떡집"]}),
        "queries": pd.DataFrame(
            {"query_id": ["q1", "q2", "q3"], "query": ["치킨", "빵", "치킨"], "split": ["val", "val", "test"]}
        ),
        "benchmark_dir": benchmark_dir,
    }


def test_evaluate_model_scores_saves_and_compares(tmp_path, inputs):
    run_root, eval_root = tmp_path / "runs", tmp_path / "eval"

    good = evaluate_model({"name": "good", "model_id": "x"}, inputs, run_root=run_root, eval_root=eval_root,
                          encoder=FakeEncoder())
    assert good["report"]["aggregate"]["nDCG@10"] == pytest.approx(1.0)
    assert (run_root / "good" / "run_t1_minimal_val.csv").exists()
    assert good["evaluation_path"].name == f"{evaluation_tag('good', 't1_minimal', 'val')}_evaluation.json"

    # 기준 모델(good) 대비 paired 비교가 붙는다
    bad = evaluate_model({"name": "bad", "model_id": "x"}, inputs, run_root=run_root, eval_root=eval_root,
                         encoder=FakeEncoder(flip=True), baseline_tag="good")
    assert bad["report"]["aggregate"]["nDCG@10"] < 1.0
    assert bad["report"]["comparison"]["baseline_tag"] == "good"
    assert "vs good" in format_report(bad["report"])

    board = collect_leaderboard(eval_root, "val")
    assert board["tag"].tolist() == ["good_t1_minimal_val", "bad_t1_minimal_val"]
    assert board.loc[1, "ΔnDCG@10"] < 0


def test_evaluate_model_reuses_doc_embeddings_and_blocks_test(tmp_path, inputs):
    encoder = FakeEncoder()
    first = evaluate_model({"name": "m", "model_id": "x"}, inputs, run_root=tmp_path / "r", eval_root=tmp_path / "e",
                           encoder=encoder)
    evaluate_model({"name": "m_prompt", "model_id": "x"}, inputs, run_root=tmp_path / "r", eval_root=tmp_path / "e",
                   encoder=encoder, doc_embeddings=first["doc_embeddings"])
    assert encoder.corpus_calls == 1

    with pytest.raises(ValueError, match="allow_test"):
        evaluate_model({"name": "m", "model_id": "x"}, inputs, run_root=tmp_path / "r", eval_root=tmp_path / "e",
                       split="test", encoder=encoder)
    result = evaluate_model({"name": "m", "model_id": "x"}, inputs, run_root=tmp_path / "r", eval_root=tmp_path / "e",
                            split="test", allow_test=True, encoder=encoder)
    assert result["report"]["query_count"] == 1


def test_unofficial_runs_are_left_out_of_leaderboard_and_manifest_gets_entry(tmp_path, inputs):
    model_dir = tmp_path / "models" / "ft"
    model_dir.mkdir(parents=True)
    (model_dir / "model_manifest.json").write_text(json.dumps({"evaluations": []}), encoding="utf-8")

    evaluate_model({"name": "ft", "model_id": str(model_dir)}, inputs, run_root=tmp_path / "r",
                   eval_root=tmp_path / "e", encoder=FakeEncoder(), official=False)
    assert collect_leaderboard(tmp_path / "e", "val").empty
    assert len(collect_leaderboard(tmp_path / "e", "val", include_unofficial=True)) == 1

    manifest = json.loads((model_dir / "model_manifest.json").read_text(encoding="utf-8"))
    assert manifest["evaluations"][0]["tag"] == "ft_t1_minimal_val"
    assert manifest["evaluations"][0]["official"] is False
