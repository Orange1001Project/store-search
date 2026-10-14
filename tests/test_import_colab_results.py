import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from store_search_ai.evaluation.model_evaluation import evaluate_model

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from import_colab_results import (
    apply_plan,
    experiment_rows,
    plan_import,
    update_experiment_registry,
    verify_imported,
)


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
    good_run = runs / "model_eval" / "good" / "run_t1_minimal_val.csv"
    good_run.with_name("run_t1_minimal_val_pre.csv").write_text(good_run.read_text(encoding="utf-8"), encoding="utf-8")
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
    assert not any(t.endswith("_pre.csv") for t in targets)  # 손으로 만든 사본은 안 가져옴
    assert "models/m_ft_a_1" in targets and "configs/models/m_ft_a_1.yaml" in targets
    assert "models/m_ft_a_2" not in targets                 # KEEP 안 한 run은 안 가져옴

    chosen = {dst.relative_to(repo).as_posix() for _, dst in plan_import(drive, repo, "bv1", models=["m_ft_a_2"])}
    assert "models/m_ft_a_2" in chosen and "models/m_ft_a_1" in chosen   # --models는 KEEP에 더해서 고름


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


def test_records_all_finetune_runs_and_experiment_table(tmp_path):
    drive, repo, _ = _drive_with_results(tmp_path)
    targets = {dst.relative_to(repo).as_posix() for _, dst in plan_import(drive, repo, "bv1", models=None)}
    # 기록 파일은 KEEP 여부와 상관없이 모든 run을 저장소에 남긴다(모델 가중치는 KEEP만)
    assert "results/finetune_runs/m_ft_a_1/model_manifest.json" in targets
    assert "results/finetune_runs/m_ft_a_2/model_manifest.json" in targets

    # 학습 모델 평가 하나를 추가해 manifest와 연결되는지 본다
    run_dir = drive / "runs" / "finetune" / "m_ft_a_1"
    (run_dir / "model_manifest.json").write_text(json.dumps({
        "owner": "a", "base_model_id": "base", "precision": "fp16", "hyperparameters": {"note": "n1"},
        "training_data": {"sha256": "abcdef0123"}, "environment": {"gpu": "T4"}}), encoding="utf-8")
    report = json.loads((drive / "runs" / "evaluation" / "good_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    report.update(tag="m_ft_a_1_t1_minimal_val", run=str(drive / "runs" / "model_eval" / "m_ft_a_1" / "run_t1_minimal_val.csv"),
                  eval_dtype="float16")
    (drive / "runs" / "evaluation" / "m_ft_a_1_t1_minimal_val_evaluation.json").write_text(json.dumps(report), encoding="utf-8")

    rows = {r["eval_tag"]: r for r in experiment_rows(drive)}
    assert set(rows) == {"good_t1_minimal_val", "m_ft_a_1_t1_minimal_val"}   # 비공식(smoke) 제외
    ft = rows["m_ft_a_1_t1_minimal_val"]
    assert (ft["kind"], ft["owner"], ft["note"], ft["train_data_sha8"], ft["precision"], ft["eval_dtype"], ft["keep"]) == (
        "fine-tuned", "a", "n1", "abcdef01", "fp16", "float16", True)
    assert rows["good_t1_minimal_val"]["kind"] == "zero-shot" and rows["good_t1_minimal_val"]["keep"] is False

    registry = repo / "results" / "experiments.csv"
    update_experiment_registry(registry, [{"eval_tag": "old_run_val", "model": "old"}])
    table = update_experiment_registry(registry, list(rows.values()))
    assert sorted(table["eval_tag"]) == ["good_t1_minimal_val", "m_ft_a_1_t1_minimal_val", "old_run_val"]  # 예전 줄 유지


def test_pruned_finetune_run_keeps_its_experiment_row(tmp_path):
    drive, repo, _ = _drive_with_results(tmp_path)
    runs = drive / "runs"
    report = json.loads((runs / "evaluation" / "good_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    for name in ("m_ft_a_2", "m_ft_a_3"):   # Drive에 평가 json은 남고 run 폴더는 prune_runs로 지워진 학습 모델
        report.update(tag=f"{name}_t1_minimal_val", run=str(runs / "model_eval" / name / "run_t1_minimal_val.csv"),
                      model_id=f"/content/drive/MyDrive/store-search-ai/runs/finetune/{name}")
        (runs / "evaluation" / f"{name}_t1_minimal_val_evaluation.json").write_text(json.dumps(report), encoding="utf-8")
    shutil.rmtree(runs / "finetune" / "m_ft_a_2")
    record = repo / "results" / "finetune_runs" / "m_ft_a_2"   # 전에 가져온 기록 파일
    record.mkdir(parents=True)
    (record / "model_manifest.json").write_text(json.dumps({"owner": "a", "precision": "fp16"}), encoding="utf-8")

    rows = {r["eval_tag"]: r for r in experiment_rows(drive, repo_root=repo)}
    assert (rows["m_ft_a_2_t1_minimal_val"]["kind"], rows["m_ft_a_2_t1_minimal_val"]["owner"]) == ("fine-tuned", "a")
    assert "m_ft_a_3_t1_minimal_val" not in rows   # manifest가 어디에도 없으면 zero-shot으로 덮어쓰지 않음
    assert rows["good_t1_minimal_val"]["kind"] == "zero-shot"

    registry = repo / "results" / "experiments.csv"
    update_experiment_registry(registry, [{"eval_tag": "m_ft_a_3_t1_minimal_val", "kind": "fine-tuned", "owner": "a"}])
    table = update_experiment_registry(registry, list(rows.values())).set_index("eval_tag")
    assert table.loc["m_ft_a_3_t1_minimal_val", "kind"] == "fine-tuned"


def test_skips_evaluations_scored_with_old_qrels_and_rescores_locally(tmp_path):
    from import_colab_results import stale_evaluations
    from rescore_evaluations import rescore_report, update_registry

    drive, repo, benchmark_dir = _drive_with_results(tmp_path)
    assert stale_evaluations(drive, benchmark_dir) == {}
    apply_plan(plan_import(drive, repo, "bv1", models=None))
    registry = repo / "results" / "experiments.csv"
    update_experiment_registry(registry, experiment_rows(drive))

    (benchmark_dir / "qrels_val.trec").write_text("q1 0 d3 3\nq2 0 d2 3\n", encoding="utf-8")   # 보충 라운드로 qrels 변경
    stale = stale_evaluations(drive, benchmark_dir)
    assert set(stale) == {"good_t1_minimal_val_evaluation.json"}
    targets = {dst.relative_to(repo).as_posix() for _, dst in plan_import(drive, repo, "bv1", None, skip=set(stale))}
    assert not any(t.endswith("_evaluation.json") for t in targets)          # 예전 점수로 덮지 않음
    assert "results/model_eval/good/run_t1_minimal_val.csv" in targets       # run 파일은 가져옴
    assert experiment_rows(drive, skip=set(stale)) == []

    local = repo / "artifacts" / "evaluation" / "bv1" / "good_t1_minimal_val_evaluation.json"
    old = json.loads(local.read_text(encoding="utf-8"))
    report, _ = rescore_report(old, repo, benchmark_dir, bootstrap=20, seed=1)
    assert report["aggregate"]["nDCG@10"] < old["aggregate"]["nDCG@10"]       # q1 정답이 바뀌어 점수가 내려감
    assert report["run"] == old["run"] and report["rescored"]["previous_aggregate"] == old["aggregate"]
    assert update_registry(registry, [report]) == 1
    row = pd.read_csv(registry, encoding="utf-8-sig").set_index("eval_tag").loc["good_t1_minimal_val"]
    assert row["nDCG@10"] == pytest.approx(report["aggregate"]["nDCG@10"])


def test_drop_inactive_queries_removes_only_those_lines_verbatim(tmp_path):
    from rescore_evaluations import drop_inactive_queries

    run = tmp_path / "run_t1_minimal_val.csv"
    text = ("\ufeffquery_id,doc_id,rank,score,system\n"
            "q1,d1,1,0.49992889165878296,m\nq_typo,d2,1,0.5,m\nq2,d3,1,0.12345678901234567,m\n")
    run.write_text(text, encoding="utf-8", newline="")
    assert drop_inactive_queries(run, {"q_typo"}) == 1
    assert run.read_text(encoding="utf-8") == text.replace("q_typo,d2,1,0.5,m\n", "")   # 점수 자릿수까지 그대로
    assert drop_inactive_queries(run, {"q_typo"}) == 0
