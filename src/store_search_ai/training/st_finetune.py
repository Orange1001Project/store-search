"""sentence-transformers Trainer로 임베딩 모델을 fine-tuning하고, 서비스에 바로 쓸 수 있는 최종
모델 하나만 Drive에 남긴다. `colab/run_finetune_simple.py`(Arctic/BGE, full fine-tuning)와
`colab/run_finetune_qwen3.py`(Qwen3-Embedding, LoRA)가 둘 다 이 `run_finetune()` 하나를 호출한다 —
팀원마다 학습 코드가 달라서 결과를 비교할 수 없게 되는 일을 막기 위해서다.

T4(무료 Colab) 기준으로 맞춘 것:
- T4는 bf16을 지원하지 않는다 → GPU가 bf16을 지원하면 bf16, 아니면 fp16 AMP를 자동 선택
  (가중치는 fp32로 두고 연산만 fp16 — 순수 fp16 학습보다 안정적). 쓴 precision은 manifest에 남는다.
- loss가 NaN/inf가 되면(fp16 overflow) 학습을 멈추고 **아무것도 Drive에 저장하지 않는다**.
- 중간 체크포인트는 전체 step의 **절반 지점에서 딱 한 번만** Drive(`<TAG>.ckpt/`)에 저장한다 —
  Colab 연결이 끊기면 `resume_tag`로 거기서부터 이어서 학습한다. 최종 모델 저장이 성공하면 지운다.
  (모델 선택용이 아니다 — 모델 선택은 로컬 공식 evaluator(14/15번)로 최종 모델끼리 비교해서 한다.)

저장 규칙 (Drive 용량 관리):
- 최종 모델만 `run_root/<TAG>/`에 저장한다: 가중치(기본 fp16 safetensors, fp32의 절반 용량) +
  sentence-transformers 설정(pooling/prompt/normalize) + `model_manifest.json` + `eval_config.yaml`.
- LoRA는 베이스 모델에 merge한 전체 모델로 저장한다 — adapter만 있는 폴더는
  `SentenceTransformer(path)`로 바로 로드할 수 없어서 평가·서빙 후보가 될 수 없다.
- 저장이 끝나면 같은 사람·같은 베이스 모델의 run은 최신 `keep_last_runs`개만 남긴다
  (`KEEP` 파일을 넣어 둔 run은 제외, `store_search_ai.training.finetune.prune_finetune_runs`).
"""

from __future__ import annotations

import gc
import json
import math
import platform
import shutil
import time
import zipfile
from dataclasses import asdict, dataclass, field
from importlib import metadata
from pathlib import Path

import yaml

from store_search_ai.pipeline.common import (
    load_config,
    sha256_file,
    write_model_manifest,
)
from store_search_ai.training.finetune import (
    CHECKPOINT_SUFFIX,
    PARTIAL_SUFFIX,
    config_mismatches,
    expand_training_rows,
    iter_package_files,
    latest_checkpoint,
    load_jsonl,
    make_run_tag,
    package_tree_sha256,
    prune_finetune_runs,
    run_tag_prefix,
    validate_resume_tag,
)

_ENV_PACKAGES = ["torch", "transformers", "sentence-transformers", "peft", "datasets", "accelerate"]


@dataclass
class FinetuneConfig:
    model_config_path: Path
    """베이스 모델의 `configs/models/*.yaml` (model_id, query_prompt_name, target_dimension을 읽음)."""
    train_pairs_path: Path
    run_root: Path
    """최종 모델이 저장될 곳(Colab에서는 Drive의 runs/finetune)."""
    owner: str
    """run 이름과 정리 범위를 정하는 사람 이름(영문 소문자). 다른 사람 run은 절대 안 지운다."""
    work_dir: Path = Path("/content/ft_work")
    """Trainer 임시 출력(로그 등). Colab 로컬 디스크 — 세션이 끝나면 사라져도 되는 것만 둔다."""

    num_epochs: int = 2
    batch_size: int = 32
    learning_rate: float = 2e-5
    warmup_ratio: float = 0.1
    weight_decay: float = 0.01
    max_seq_length: int = 128
    """문서 텍스트는 평균 24자, Qwen3 instruction을 붙인 query도 수십 토큰이라 128이면 충분."""
    num_hard_negatives: int = 3
    max_positives_per_query: int | None = 32
    loss: str = "gist"
    """"gist": GISTEmbedLoss(베이스 모델을 guide로 in-batch false negative를 걸러냄) /
    "mnrl": MultipleNegativesRankingLoss. 같은 family의 query가 한 배치에 섞이면 서로의 정답이
    오답으로 취급되는데(예: "국밥"과 "순대국"), gist가 그걸 걸러준다. 메모리가 부족하면 mnrl."""
    query_prompt_override: str | None = None
    """None이면 베이스 모델의 `query_prompt_name` prompt를 그대로 쓴다. 문자열을 주면 그 prompt로
    학습하고, 저장되는 모델의 같은 prompt 이름에도 그 문자열을 기록한다 — 그래서 평가/서빙에서
    `prompt_name`만 쓰면 학습 때와 똑같은 prompt가 자동으로 붙는다."""

    lora_rank: int | None = None
    """None이면 full fine-tuning. 값을 주면 LoRA로 학습한 뒤 merge해서 전체 모델로 저장."""
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    base_dtype: str = "float32"
    """학습할 때 베이스 가중치 dtype. T4에서 Qwen3-4B처럼 fp32로 안 올라가는 모델만 "float16"
    (LoRA 전용 — 학습되는 LoRA 파라미터는 항상 fp32로 둔다)."""
    save_dtype: str = "float16"
    """Drive에 저장할 dtype. fp16이면 용량이 fp32의 절반이고 검색 성능 차이는 사실상 없다."""

    seed: int = 20260831
    save_mid_checkpoint: bool = True
    """전체 step의 절반에서 한 번 Drive에 체크포인트(모델+optimizer)를 저장한다. 크기: LoRA는 수십 MB,
    full fine-tuning(Arctic/BGE)은 약 7GB(fp32 가중치+Adam 상태) — 최종 저장 성공 시 지워지지만 학습 도중에는
    그만큼 Drive 여유 공간이 필요하다. 공간이 없으면 False(끊기면 처음부터 다시)."""
    resume_tag: str | None = None
    """끊긴 run을 이어서 학습할 때 그 run의 TAG(예: "bge_m3_ft_jisu_20260928_0307"). 나머지 설정은
    처음 실행과 같아야 한다(다르면 거부 — `RESUME_IGNORED_KEYS`만 예외)."""
    keep_last_runs: int = 3
    note: str = ""
    """이 run에서 무엇을 왜 바꿨는지 한 줄. 모델 폴더 밖에서 하는 처리(쿼리 전처리 추가 등)를 했다면
    서비스도 똑같이 해야 하므로 `서비스도 필요:`로 시작해서 적는다(`docs/TRAINING_TEAM.md` 4절)."""
    extra: dict = field(default_factory=dict)
    """manifest에 그대로 남길 추가 메모(실험 목적 등)."""


class _NonFiniteLossError(RuntimeError):
    pass


def _environment(torch) -> dict:
    packages = {}
    for name in _ENV_PACKAGES:
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "python": platform.python_version(),
        "packages": packages,
        "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }


def _pick_precision(torch) -> str:
    if not torch.cuda.is_available():
        return "fp32"
    return "bf16" if torch.cuda.is_bf16_supported() else "fp16"


def _training_data_record(path: Path, expand_stats: dict) -> dict:
    record = {
        "source": path.as_posix(),
        "sha256": sha256_file(path),
        "expansion": expand_stats,
    }
    meta_path = path.with_suffix(".meta.json")
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        record["prepare_meta"] = meta
        if meta.get("train_pairs_sha256") != record["sha256"]:
            print(
                "[경고] train_pairs.jsonl의 sha256이 meta.json과 다릅니다 — jsonl만 다시 만들고 "
                "meta.json은 옛 것을 올린 것 같습니다. 둘을 같이 다시 올리세요."
            )
            record["prepare_meta_mismatch"] = True
    else:
        print(f"[경고] {meta_path.name} 없음 — 어떤 qrels로 만든 데이터인지 manifest에 안 남습니다.")
    return record


_PACKAGE_DIR = Path(__file__).resolve().parents[1]
"""지금 import된 `store_search_ai` 패키지 폴더 — Colab에서는 Drive의 project/src/store_search_ai."""


def _save_code_snapshot(model_dir: Path) -> dict:
    """학습에 실제로 쓴 코드를 모델 폴더에 zip으로 남기고, `pack_for_colab.py`가 적은 git 정보를 읽어온다.

    Colab에는 git이 없어서 사람이 커밋 번호를 적어야 했는데, 잊거나 틀리기 쉽다. 코드 사본을 모델 옆에 두면
    커밋을 안 했더라도 나중에 "이 모델은 정확히 이 코드로 학습됐다"를 그대로 확인·재현할 수 있다.
    """

    snapshot_path = model_dir / "code_snapshot.zip"
    with zipfile.ZipFile(snapshot_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in iter_package_files(_PACKAGE_DIR):
            zf.write(path, Path("store_search_ai") / path.relative_to(_PACKAGE_DIR))

    tree_sha256 = package_tree_sha256(_PACKAGE_DIR)
    version_path = _PACKAGE_DIR.parents[1] / "code_version.json"
    edited_after_pack = None
    if version_path.exists():
        version = json.loads(version_path.read_text(encoding="utf-8"))
        edited_after_pack = version.get("src_tree_sha256") != tree_sha256
        if edited_after_pack:
            print(
                "[안내] Drive에 올린 뒤 Colab에서 고친 코드로 학습했습니다 — 정확한 코드는 모델 폴더의 "
                "code_snapshot.zip에 있습니다(좋은 결과면 이걸 로컬에 풀어서 커밋, docs/TRAINING_TEAM.md 3절)."
            )
    else:
        version = None
        print("[안내] code_version.json 없음 — scripts/pack_for_colab.py로 올리면 git 커밋 정보도 자동으로 남습니다.")
    return {
        "version": version,
        "edited_after_pack": edited_after_pack,
        "src_tree_sha256": tree_sha256,
        "snapshot": snapshot_path.name,
        "snapshot_sha256": sha256_file(snapshot_path),
    }


def _config_record(cfg: FinetuneConfig) -> dict:
    record = asdict(cfg)
    for key in ("model_config_path", "train_pairs_path", "run_root", "work_dir"):
        record[key] = Path(record[key]).as_posix()
    return record


def run_finetune(cfg: FinetuneConfig) -> Path:
    """학습 → (LoRA면 merge) → 저장 → 재로드 검증 → manifest → 오래된 run 정리. 최종 폴더를 반환."""

    import torch
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )
    from sentence_transformers.training_args import BatchSamplers
    from transformers import TrainerCallback, set_seed

    set_seed(cfg.seed)
    model_config = load_config(cfg.model_config_path)
    base_name = model_config["name"]
    if cfg.resume_tag:
        tag = validate_resume_tag(cfg.resume_tag, base_name, cfg.owner)
    else:
        tag = make_run_tag(base_name, cfg.owner)
    cfg.run_root.mkdir(parents=True, exist_ok=True)
    final_dir = cfg.run_root / tag
    partial_dir = cfg.run_root / f"{tag}{PARTIAL_SUFFIX}"
    checkpoint_root = cfg.run_root / f"{tag}{CHECKPOINT_SUFFIX}"
    if final_dir.exists():
        raise SystemExit(f"{final_dir}가 이미 있습니다 — 이미 끝난 run이거나, 1분 안에 다시 실행했습니다.")
    if partial_dir.exists():
        shutil.rmtree(partial_dir)  # 지난번 최종 저장 도중 끊긴 것 — 이번에 다시 저장한다

    # 체크포인트에는 이 설정 + 학습 데이터 해시를 같이 남겨서, 이어서 학습할 때 설정이나 데이터가
    # 바뀌었으면 거부한다(바뀐 채로 이어 붙이면 어떤 설정의 결과인지 알 수 없는 모델이 나온다).
    run_config = {**_config_record(cfg), "train_pairs_sha256": sha256_file(cfg.train_pairs_path)}
    resume_from = None
    if cfg.resume_tag:
        resume_from = latest_checkpoint(checkpoint_root)
        if resume_from is None:
            raise SystemExit(
                f"{checkpoint_root}에 checkpoint-N이 없습니다 — 중간 저장 전에 끊긴 run은 처음부터 다시 돌리세요."
            )
        saved_config = json.loads((checkpoint_root / "finetune_config.json").read_text(encoding="utf-8"))
        mismatches = config_mismatches(saved_config, run_config)
        if mismatches:
            details = ", ".join(f"{k}: {saved_config.get(k)!r} -> {run_config.get(k)!r}" for k in mismatches)
            raise SystemExit(f"처음 실행과 설정/데이터가 다릅니다 — 처음 값으로 되돌리세요: {details}")
        print(f"[INFO] 이어서 학습: {resume_from}")
    elif cfg.save_mid_checkpoint:
        checkpoint_root.mkdir()
        (checkpoint_root / "finetune_config.json").write_text(
            json.dumps(run_config, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
        )
    use_checkpoints = cfg.save_mid_checkpoint or resume_from is not None

    precision = _pick_precision(torch)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"[INFO] run: {tag}  base: {model_config['model_id']}  precision: {precision}  device: {device}")

    # ---------------- 데이터 ----------------
    records = load_jsonl(cfg.train_pairs_path)
    rows, expand_stats = expand_training_rows(
        records, cfg.num_hard_negatives, cfg.max_positives_per_query
    )
    print(f"[INFO] 학습 데이터: {expand_stats}")
    if not rows:
        raise SystemExit("학습 행이 0개입니다 — train_pairs.jsonl 또는 NUM_HARD_NEGATIVES를 확인하세요.")
    train_dataset = Dataset.from_list(rows)

    # ---------------- 모델 ----------------
    base_dtype = getattr(torch, cfg.base_dtype)
    model = SentenceTransformer(
        model_config["model_id"], device=device, model_kwargs={"torch_dtype": base_dtype}
    )
    model.max_seq_length = cfg.max_seq_length

    prompt_name = model_config.get("query_prompt_name")
    # yaml에 query_prompt(문자열)가 있으면(prompt 실험용 yaml) 그 prompt로 학습한다 — 저장되는 모델의 prompt에도
    # 기록되므로 eval_config.yaml은 prompt_name만으로 같은 문자열을 쓰게 된다.
    if cfg.query_prompt_override is None and model_config.get("query_prompt"):
        cfg.query_prompt_override = model_config["query_prompt"]
    if cfg.query_prompt_override is not None:
        prompt_name = prompt_name or "query"
        model.prompts[prompt_name] = cfg.query_prompt_override
    if prompt_name and prompt_name not in model.prompts:
        raise SystemExit(
            f"query_prompt_name={prompt_name!r}가 이 모델의 prompts {list(model.prompts)}에 없습니다."
        )
    query_prompt = model.prompts[prompt_name] if prompt_name else None
    print(f"[INFO] query prompt ({prompt_name}): {query_prompt!r}")

    if cfg.lora_rank is not None:
        from peft import LoraConfig, TaskType, get_peft_model

        transformer = model[0]
        transformer.auto_model = get_peft_model(
            transformer.auto_model,
            LoraConfig(
                task_type=TaskType.FEATURE_EXTRACTION,
                r=cfg.lora_rank,
                lora_alpha=cfg.lora_alpha,
                lora_dropout=cfg.lora_dropout,
                target_modules="all-linear",
            ),
        )
        # fp16 베이스에 붙은 LoRA 파라미터도 fp16이 되는데, fp16 파라미터는 AMP GradScaler가
        # unscale할 수 없어 에러가 난다 → 학습되는 파라미터만 fp32로 올린다.
        for param in transformer.auto_model.parameters():
            if param.requires_grad:
                param.data = param.data.float()
        transformer.auto_model.print_trainable_parameters()

    # ---------------- loss ----------------
    guide = None
    if cfg.loss == "gist":
        guide = SentenceTransformer(
            model_config["model_id"],
            device=device,
            model_kwargs={"torch_dtype": torch.float16 if device == "cuda" else torch.float32},
        )
        guide.max_seq_length = cfg.max_seq_length
        guide.eval()
        train_loss = losses.GISTEmbedLoss(model, guide=guide)
    elif cfg.loss == "mnrl":
        train_loss = losses.MultipleNegativesRankingLoss(model)
    else:
        raise ValueError(f"loss는 'gist' 또는 'mnrl': {cfg.loss!r}")

    target_dim = model_config.get("target_dimension")
    full_dim = model.get_sentence_embedding_dimension()
    if target_dim and target_dim < full_dim:
        # 평가/서빙은 앞 target_dim 차원만 쓰므로(configs/models의 target_dimension), 그 차원에서도
        # 성능이 유지되도록 Matryoshka로 두 차원을 함께 학습한다.
        train_loss = losses.MatryoshkaLoss(model, train_loss, matryoshka_dims=[full_dim, target_dim])

    # ---------------- 학습 ----------------
    non_finite_steps = []

    class NonFiniteLossGuard(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            loss = (logs or {}).get("loss")
            if loss is not None and not math.isfinite(loss):
                non_finite_steps.append(state.global_step)
                control.should_training_stop = True

    mid_checkpoint_steps = []

    class SaveOnceAtMidpoint(TrainerCallback):
        # save_strategy="no"라 Trainer가 알아서 저장하지는 않고, 절반 step에서 이 callback이 한 번만 저장을 요청한다.
        def on_step_end(self, args, state, control, **kwargs):
            if state.global_step == max(1, state.max_steps // 2):
                mid_checkpoint_steps.append(state.global_step)
                control.should_save = True

        def on_save(self, args, state, control, **kwargs):
            print(
                f"\n[체크포인트] step {state.global_step}/{state.max_steps} 저장 완료: "
                f"{checkpoint_root.name}/checkpoint-{state.global_step} — 여기서 끊겨도 RESUME_TAG=\"{tag}\"로 이어서 학습 가능"
            )

    lora = cfg.lora_rank is not None

    class Trainer(SentenceTransformerTrainer):
        def _load_from_checkpoint(self, checkpoint_path, model=None):
            if not lora:
                return super()._load_from_checkpoint(checkpoint_path)
            # 기본 구현은 체크포인트를 SentenceTransformer로 통째로 한 벌 더 GPU에 올린다(4B+T4면 OOM).
            # LoRA는 학습된 adapter 가중치만 읽어서 지금 모델에 넣는다.
            from peft import set_peft_model_state_dict
            from safetensors.torch import load_file

            adapter_state = load_file(str(Path(checkpoint_path) / "adapter_model.safetensors"))
            result = set_peft_model_state_dict(self.model[0].auto_model, adapter_state)
            if not adapter_state or result.unexpected_keys:
                raise RuntimeError(
                    f"LoRA 체크포인트를 읽지 못했습니다: {checkpoint_path} ({result.unexpected_keys[:5]})"
                )

    output_dir = checkpoint_root if use_checkpoints else cfg.work_dir / tag
    args = SentenceTransformerTrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=cfg.num_epochs,
        per_device_train_batch_size=cfg.batch_size,
        learning_rate=cfg.learning_rate,
        warmup_ratio=cfg.warmup_ratio,
        weight_decay=cfg.weight_decay,
        fp16=precision == "fp16",
        bf16=precision == "bf16",
        batch_sampler=BatchSamplers.NO_DUPLICATES,
        prompts={"anchor": query_prompt} if query_prompt else None,
        save_strategy="no",
        save_total_limit=1,
        eval_strategy="no",
        logging_steps=10,
        report_to="none",
        seed=cfg.seed,
        data_seed=cfg.seed,
    )
    callbacks = [NonFiniteLossGuard()]
    if cfg.save_mid_checkpoint:
        callbacks.append(SaveOnceAtMidpoint())
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=train_dataset,
        loss=train_loss,
        callbacks=callbacks,
    )
    started = time.time()
    trainer.train(resume_from_checkpoint=str(resume_from) if resume_from else None)
    runtime_sec = round(time.time() - started, 1)

    if non_finite_steps:
        raise _NonFiniteLossError(
            f"step {non_finite_steps[0]}에서 loss가 NaN/inf가 되어 학습을 중단했습니다(fp16 overflow 가능성). Drive에는 아무것도 저장하지 "
            "않았습니다. LEARNING_RATE를 낮추거나(예: 절반), bf16을 지원하는 GPU(L4/A100)를 쓰세요."
            + (f" (NaN 이전 체크포인트 {checkpoint_root.name}는 남아 있습니다 — 필요 없으면 삭제)"
               if checkpoint_root.exists() else "")
        )
    loss_history = [
        {"step": log["step"], "loss": round(log["loss"], 5)}
        for log in trainer.state.log_history
        if "loss" in log
    ]
    global_steps = trainer.state.global_step

    # 학습용 객체(optimizer 상태, GIST guide 모델)를 GPU에서 내린다 — 아래 검증에서 저장한 모델을 한 벌 더
    # 올리는데, 이걸 안 하면 4B+T4처럼 빠듯한 경우 학습을 다 끝내고 마지막 저장 단계에서 OOM이 난다.
    del trainer, train_loss, guide
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    # ---------------- 저장 (partial → 검증 → 최종 이름) ----------------
    if cfg.lora_rank is not None:
        model[0].auto_model = model[0].auto_model.merge_and_unload()
    model.to(getattr(torch, cfg.save_dtype))
    model.save(str(partial_dir), safe_serialization=True)

    _verify_reload(model, partial_dir, prompt_name, device, SentenceTransformer, torch)

    eval_config = {
        "name": tag,
        "model_id": f"models/{tag}",
        "query_prompt_name": prompt_name,
        "normalize_embeddings": model_config.get("normalize_embeddings", True),
        "target_dimension": target_dim,
        "batch_size": model_config.get("batch_size", 32),
    }
    if model_config.get("torch_dtype"):
        eval_config["torch_dtype"] = model_config["torch_dtype"]  # 베이스 yaml과 같은 dtype으로 평가(4B+T4 OOM 방지)
    (partial_dir / "eval_config.yaml").write_text(
        yaml.safe_dump(eval_config, allow_unicode=True, sort_keys=False), encoding="utf-8", newline="\n"
    )

    hyperparameters = _config_record(cfg)
    training_data = _training_data_record(cfg.train_pairs_path, expand_stats)
    code_record = _save_code_snapshot(partial_dir)
    write_model_manifest(
        partial_dir,
        {
            "tag": tag,
            "owner": cfg.owner,
            "base_model_id": model_config["model_id"],
            "base_model_config": model_config,
            "framework": "sentence-transformers" + ("+peft-lora(merged)" if cfg.lora_rank else ""),
            "hyperparameters": hyperparameters,
            "precision": precision,
            "training_data": training_data,
            "code": code_record,
            "training_result": {
                "runtime_sec": runtime_sec,  # 이어서 학습했다면 마지막 세션의 시간만
                "resumed_from": resume_from.name if resume_from else None,
                "mid_checkpoint_step": mid_checkpoint_steps[0] if mid_checkpoint_steps else None,
                "global_steps": global_steps,
                "final_loss": loss_history[-1]["loss"] if loss_history else None,
                "loss_history": loss_history,
            },
            "serving": {
                # 학습 데이터를 만든 template(prepare_finetune_dataset.py --template) — 서비스 인덱싱도 같은 template
                "document_template": training_data.get("prepare_meta", {}).get("template"),
                "query_prompt_name": prompt_name,
                "query_prompt": query_prompt,
                "document_prompt": None,
                "embedding_dim": target_dim or full_dim,
                "full_embedding_dim": full_dim,
                "normalize_embeddings": eval_config["normalize_embeddings"],
                "similarity": "cosine",
                "max_seq_length": cfg.max_seq_length,
                "saved_dtype": cfg.save_dtype,
            },
            "environment": _environment(torch),
        },
    )
    partial_dir.rename(final_dir)
    print(f"[완료] 최종 모델: {final_dir}")
    if checkpoint_root.exists():
        shutil.rmtree(checkpoint_root)
        print(f"[정리] 중간 체크포인트 삭제: {checkpoint_root.name}")

    deleted = prune_finetune_runs(cfg.run_root, run_tag_prefix(base_name, cfg.owner), cfg.keep_last_runs)
    for run_dir in deleted:
        print(f"[정리] 오래된 run 삭제: {run_dir.name}")
    prefix = run_tag_prefix(base_name, cfg.owner)
    leftovers = [
        d.name
        for suffix in (PARTIAL_SUFFIX, CHECKPOINT_SUFFIX)
        for d in cfg.run_root.glob(f"{prefix}*{suffix}")
    ]
    if leftovers:
        print(
            f"[경고] 끝나지 않은 run의 폴더가 남아 있습니다: {leftovers} — .ckpt는 RESUME_TAG로 이어서 "
            "학습하거나, 필요 없으면 직접 삭제하세요(자동 정리 대상이 아님)."
        )
    return final_dir


def _verify_reload(model, saved_dir: Path, prompt_name, device, SentenceTransformer, torch) -> None:
    """저장한 폴더를 새로 로드해서 메모리의 모델과 같은 임베딩이 나오는지 확인한다.

    pooling 설정이나 prompt가 빠진 채 저장되면(예: merge 후 sentence-transformers 설정 누락)
    로드는 되지만 조용히 다른 임베딩이 나온다 — 그런 체크포인트를 평가/서빙에 넘기지 않기 위한 검사.
    """

    queries = ["국밥", "24시 약국", "아이 옷 가게"]
    docs = ["가맹점명: 할매순대국 / 취급품목: 한식", "가맹점명: 온누리약국 / 취급품목: 의약품"]
    cases = [(queries, {"prompt_name": prompt_name} if prompt_name else {}), (docs, {})]

    # 메모리의 모델로 기준 임베딩을 먼저 뽑고 CPU로 내린 뒤에 저장본을 올린다(GPU에 모델 두 벌이 동시에 안 있게).
    expected = [
        model.encode(texts, normalize_embeddings=True, convert_to_tensor=True, **kwargs).float().cpu()
        for texts, kwargs in cases
    ]
    model.to("cpu")
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    reloaded = SentenceTransformer(str(saved_dir), device=device)
    for (texts, kwargs), a in zip(cases, expected):
        b = reloaded.encode(texts, normalize_embeddings=True, convert_to_tensor=True, **kwargs).float().cpu()
        min_cos = torch.nn.functional.cosine_similarity(a, b).min().item()
        if min_cos < 0.999:
            raise RuntimeError(
                f"저장된 모델을 다시 로드하니 임베딩이 달라졌습니다(min cosine={min_cos:.4f}). "
                f"{saved_dir}는 평가/서빙에 쓰면 안 됩니다."
            )
    print("[검증] 저장된 모델 재로드 임베딩 일치 확인")
    del reloaded
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
