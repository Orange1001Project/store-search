import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.evaluation.model_evaluation import evaluate_model

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from import_colab_results import apply_plan, plan_import, verify_imported


class _Encoder:
    def __init__(self):
        self.config = {}

    def encode_corpus(self, texts):
        return np.eye(len(texts), dtype="float32")

    def encode_queries(self, texts):
        return np.eye(len(texts), 3, dtype="float32")


def _drive_with_results(tmp_path):
    """Colab이 Drive에 남기는 것과 같은 레이아웃을 evaluate_model로 실제로 만든다."""

    benchmark_dir = tmp_path / "repo" / "benchmark"
    benchmark_dir.mkdir(parents=True)
    (benchmark_dir / "qrels_val.trec").write_text("q1 0 d1 3\nq2 0 d2 3\n", encoding="utf-8")
    inputs = {
        "config": {"evaluation": {"bootstrap_samples": 20, "random_seed": 1}},
        "corpus": pd.DataFrame({"doc_id": ["d1", "d2", "d3"], "search_text_t1_minimal": ["a", "b", "c"]}),
        "queries": pd.DataFrame({"query_id": ["q1", "q2"], "query": ["x", "y"], "split": ["val", "val"]}),
        "benchmark_dir": benchmark_dir,
    }
    runs = tmp_path / "drive" / "runs"
    evaluate_model({"name": "good", "model_id": "x"}, inputs, run_root=runs / "model_eval",
                   eval_root=runs / "evaluation", encoder=_Encoder())
    evaluate_model({"name": "smoke", "model_id": "x"}, inputs, run_root=runs / "model_eval",
                   eval_root=runs / "evaluation", encoder=_Encoder(), official=False)
    for name, keep in (("m_ft_a_1", True), ("m_ft_a_2", False)):
        run_dir = runs / "finetune" / name
        run_dir.mkdir(parents=True)
        (run_dir / "model_manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "eval_config.yaml").write_text(f"name: {name}\nmodel_id: models/{name}\n", encoding="utf-8")
        if keep:
            (run_dir / "KEEP").write_text("", encoding="utf-8")
    return tmp_path / "drive", tmp_path / "repo", benchmark_dir


def test_plan_skips_unofficial_and_copies_only_kept_models(tmp_path):
    drive, repo, _ = _drive_with_results(tmp_path)
    plan = plan_import(drive, repo, "bv1", models=None)
    targets = {dst.relative_to(repo).as_posix() for _, dst in plan}
    assert "artifacts/evaluation/bv1/good_t1_minimal_val_evaluation.json" in targets
    assert "results/model_eval/good/run_t1_minimal_val.csv" in targets
    assert not any("smoke" in t for t in targets)          # 비공식(smoke) 평가는 안 가져옴
    assert "models/m_ft_a_1" in targets and "configs/models/m_ft_a_1.yaml" in targets
    assert "models/m_ft_a_2" not in targets                 # KEEP 안 한 run은 안 가져옴

    chosen = {dst.relative_to(repo).as_posix() for _, dst in plan_import(drive, repo, "bv1", models=["m_ft_a_2"])}
    assert "models/m_ft_a_2" in chosen and "models/m_ft_a_1" not in chosen


def test_verify_matches_local_rescoring_and_flags_changed_qrels(tmp_path):
    drive, repo, benchmark_dir = _drive_with_results(tmp_path)
    plan = plan_import(drive, repo, "bv1", models=None)
    apply_plan(plan)
    eval_files = [dst for _, dst in plan if dst.name.endswith("_evaluation.json")]
    assert verify_imported(repo, benchmark_dir, eval_files, bootstrap=20, seed=1) == []

    (benchmark_dir / "qrels_val.trec").write_text("q1 0 d3 3\nq2 0 d2 3\n", encoding="utf-8")  # 정답이 바뀐 경우
    problems = verify_imported(repo, benchmark_dir, eval_files, bootstrap=20, seed=1)
    assert problems and "다름" in problems[0]
    assert json.loads(eval_files[0].read_text(encoding="utf-8"))["official"] is True
