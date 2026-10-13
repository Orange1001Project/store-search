import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0), round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
else:
    print("[경고] GPU가 없습니다 — 런타임 > 런타임 유형 변경 > GPU")

# ---- cell ----
# - torchao: Colab 기본 0.10이 깔려 있는데 peft 0.21은 torchao가 있으면 0.16 이상을 요구해서 LoRA를 붙일 때
#   ImportError가 난다. 이 노트북은 torchao를 쓰지 않으므로 지운다.
# - transformers/sentence-transformers/peft/datasets/accelerate는 Colab 기본 버전을 그대로 쓴다(다운그레이드하면
#   huggingface_hub·fsspec까지 내려가 Colab 기본 패키지와 충돌). 버전 차이는 "2. 호환" 셀이 맞춘다.
# - 채점용 두 개만 설치(HF 패키지를 건드리지 않음).
get_ipython().system('pip -q uninstall -y torchao')
# - GPU 메모리 조각화로 인한 OOM 완화(torch가 GPU를 처음 쓰기 전에 설정돼야 함)
import os

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
get_ipython().system('pip -q install "ir-measures==0.4.3" "pytrec-eval-terrier==0.5.10"')

# ---- cell ----
from google.colab import drive

drive.mount("/content/drive")

# ---- cell ----
# @cell settings
import re
from pathlib import Path

OWNER = "kse1"                 # 필수: 영문 소문자로 시작하는 2~16자(소문자·숫자), 예 "jisu"
MODEL = "qwen3_0_6b"       # MODEL_PRESETS의 키
NOTE = ""                  # 기본값에서 바꾼 것 한 줄. 모델 밖 처리(쿼리 전처리 등)를 넣었으면 "서비스도 필요: ..."로 시작
SMOKE = True              # True: 가짜 학습 데이터 + 축소 코퍼스로 전체 흐름만 확인(결과는 runs_smoke/, 비공식)
RESUME_TAG = None          # Colab이 끊겨 이어서 학습할 때만: 로그의 [체크포인트] RESUME_TAG 값
SAVE_MID_CHECKPOINT = True # 학습 절반에서 한 번 Drive 저장(Arctic/BGE는 약 7GB, 끝나면 자동 삭제). 공간 없으면 False
EVAL_RUN_TAG = None        # 학습 없이 평가만: Drive runs/finetune/ 의 TAG
FINAL_TEST = False         # 팀이 최종 후보를 정한 뒤에만 True(test 채점)

STORE_PROMPT = ("Instruct: Given a Korean local-store search query, retrieve stores that satisfy the user's shopping, "
                "dining, or service intent\nQuery:")
MODEL_PRESETS = {
    # name: 결과 폴더/리더보드에 쓰는 이름(저장소 configs/models/*.yaml의 name과 같음)
    # train: 이 모델의 학습 기본값(LoRA 여부, lr, 베이스 dtype, batch, loss, mini_batch_size)
    "arctic_ko": {"name": "snowflake_arctic_embed_l_v2_ko", "model_id": "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
                      "query_prompt_name": None, "batch_size": 32,
                      "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "arctic_ko_query": {"name": "snowflake_arctic_embed_l_v2_ko_query", "model_id": "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
                            "query_prompt_name": "query", "batch_size": 32,
                            "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "bge_m3": {"name": "bge_m3", "model_id": "BAAI/bge-m3", "query_prompt_name": None, "batch_size": 32,
                   "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "qwen3_0_6b": {"name": "qwen3_embedding_0_6b", "model_id": "Qwen/Qwen3-Embedding-0.6B", "query_prompt_name": "query",
                       "batch_size": 32,
                       "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "qwen3_0_6b_store": {"name": "qwen3_embedding_0_6b_store", "model_id": "Qwen/Qwen3-Embedding-0.6B",
                             "query_prompt": STORE_PROMPT, "batch_size": 32,
                             "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    # 4B: T4(15GB)면 fp16 베이스 + batch 8 + mnrl. 평가도 fp16으로 올리고 앞 1024차원만 쓴다(Matryoshka로 학습)
    "qwen3_4b": {"name": "qwen3_embedding_4b", "model_id": "Qwen/Qwen3-Embedding-4B", "query_prompt_name": "query",
                     "batch_size": 8, "target_dimension": 1024, "torch_dtype": "float16",
                     "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float16", "batch_size": 8, "loss": "mnrl", "mini_batch_size": 4}},
    "qwen3_4b_store": {"name": "qwen3_embedding_4b_store", "model_id": "Qwen/Qwen3-Embedding-4B", "query_prompt": STORE_PROMPT,
                           "batch_size": 8, "target_dimension": 1024, "torch_dtype": "float16",
                           "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float16", "batch_size": 8, "loss": "mnrl", "mini_batch_size": 4}},
}

preset = MODEL_PRESETS[MODEL]
HP = {                       # 학습 설정 — 팀 공통 기본값(모델별 값은 preset["train"]에서)
    "num_epochs": 2,
    "batch_size": preset["train"]["batch_size"],   # 한 step의 in-batch negative 수(결과에 영향) — 팀 기준값 유지
    "mini_batch_size": preset["train"]["mini_batch_size"],  # GPU에 한 번에 올리는 문장 수(메모리만, 결과 동일). OOM이면 절반으로
    "learning_rate": preset["train"]["learning_rate"],
    "warmup_ratio": 0.1,
    "weight_decay": 0.01,
    "max_seq_length": 128,          # 문서 평균 24자 — 128이면 충분
    "num_hard_negatives": 3,        # 6 이하 권장(7 이상이면 negative가 적은 일부 쿼리가 빠짐)
    "max_positives_per_query": 32,
    "loss": preset["train"]["loss"],          # "gist"(같은 계열 쿼리끼리 정답을 오답으로 배우는 문제 완화) / "mnrl"
    "lora_rank": preset["train"]["lora_rank"],  # None이면 full fine-tuning
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "base_dtype": preset["train"]["base_dtype"],
    "save_dtype": "float16",        # Drive에 저장할 dtype(fp32의 절반 용량)
    "seed": 20260831,
    "keep_last_runs": 3,            # 내 run 중 같은 모델 최신 N개만 Drive에 남김(KEEP 파일 있는 run은 보존)
}

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
DATA_DIR = DRIVE_ROOT / "data"
RUNS = DRIVE_ROOT / ("runs_smoke" if SMOKE else "runs")
FINETUNE_DIR, RUN_DIR, EVAL_DIR = RUNS / "finetune", RUNS / "model_eval", RUNS / "evaluation"
WORK_DIR = Path("/content/ft_work")
OFFICIAL = not SMOKE

if SMOKE:
    OWNER = OWNER or "smoke"
if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", OWNER):
    raise ValueError("OWNER를 영문 소문자로 시작하는 2~16자(소문자·숫자)로 적으세요, 예: 'jisu'")
print(f"[설정] MODEL={MODEL} ({preset['model_id']})  OWNER={OWNER}  SMOKE={SMOKE}  → {RUNS}")

# ---- cell ----
# @cell compat
import dataclasses
from importlib import metadata

LIBRARIES = ["torch", "transformers", "sentence-transformers", "peft", "datasets", "accelerate",
             "huggingface-hub", "ir-measures", "pytrec-eval-terrier"]
MINIMUM_VERSIONS = {"transformers": (4, 51), "sentence-transformers": (3, 3), "peft": (0, 13), "datasets": (2, 19),
                    "accelerate": (0, 26)}
TESTED_MAJOR = {"transformers": 5, "sentence-transformers": 5}


def version_tuple(package):
    try:
        raw = metadata.version(package)
    except metadata.PackageNotFoundError:
        return None
    parts = []
    for piece in raw.split("+")[0].split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def library_versions():
    versions = {}
    for name in LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def check_environment():
    versions = library_versions()
    problems = []
    for package, minimum in MINIMUM_VERSIONS.items():
        found = version_tuple(package)
        if found is None:
            problems.append(f"{package} 없음 — !pip install {package}")
        elif found[: len(minimum)] < minimum:
            problems.append(f"{package} {versions.get(package)} < {'.'.join(map(str, minimum))}")
    for package in ("ir-measures", "pytrec-eval-terrier"):
        if versions.get(package) is None:
            problems.append(f"{package} 없음 — 설치 셀을 다시 실행")
    for package, major in TESTED_MAJOR.items():
        found = version_tuple(package)
        if found and found[0] > major:
            print(f"[경고] {package} {versions.get(package)}: 확인된 적 없는 메이저 버전 — SMOKE=True로 먼저 확인하세요")
    print("[환경] " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    if problems:
        raise RuntimeError("Colab 환경 문제: " + "; ".join(problems))
    return versions


def dtype_kwargs(dtype):
    return {"dtype": dtype} if (version_tuple("transformers") or (0,)) >= (4, 56) else {"torch_dtype": dtype}


def set_transformer_model(module, model):
    attribute = getattr(type(module), "auto_model", None)
    if isinstance(attribute, property) and attribute.fset is None:   # sentence-transformers 5
        module.model = model
    else:
        module.auto_model = model


def warmup_kwargs(training_args_class, ratio):
    fields = {field.name for field in dataclasses.fields(training_args_class)}
    return {"warmup_ratio": ratio} if "warmup_ratio" in fields else {"warmup_steps": ratio}


def batch_samplers():
    try:
        from sentence_transformers.base.sampler import BatchSamplers
    except ImportError:
        from sentence_transformers.training_args import BatchSamplers
    return BatchSamplers


def losses_module():
    try:
        from sentence_transformers.sentence_transformer import losses
    except ImportError:
        from sentence_transformers import losses
    return losses


def embedding_dimension(model):
    method = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return method()

# ---- cell ----
VERSIONS = check_environment()

# ---- cell ----
import hashlib
import json

import numpy as np
import pandas as pd


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


DATA_VERSION = json.loads((DATA_DIR / "data_version.json").read_text(encoding="utf-8"))
EVAL_SETTINGS = DATA_VERSION["evaluation"]          # bootstrap 횟수·seed(저장소 configs/benchmark와 같은 값)
corpus = pd.read_parquet(DATA_DIR / DATA_VERSION["corpus_file"])
queries = pd.read_csv(DATA_DIR / "queries.csv", encoding="utf-8-sig")
queries = queries[queries["status"].astype(str).str.lower() == "active"].reset_index(drop=True)
QRELS = {split: DATA_DIR / f"qrels_{split}.trec" for split in ("val", "test")}

if SMOKE:
    judged = {line.split()[2] for line in QRELS["val"].read_text(encoding="utf-8").splitlines() if line.strip()}
    corpus = pd.concat([corpus[corpus["doc_id"].isin(judged)],
                        corpus[~corpus["doc_id"].isin(judged)].sample(2000, random_state=0)]).reset_index(drop=True)
    TRAIN_PAIRS = Path("/content/smoke_train_pairs.jsonl")
    with TRAIN_PAIRS.open("w", encoding="utf-8", newline="\n") as f:
        for i in range(40):   # query 40개 × positive 4개 = 160행(10 step) — 흐름 확인용이라 짧게, 텍스트는 전부 서로 다르게
            f.write(json.dumps({
                "query_id": f"smoke_{i}", "query": f"테스트 질의 {i}번 매장",
                "positives": [f"가맹점명: 정답매장{i}-{j} / 취급품목: 품목{i}" for j in range(4)],
                "negatives": [f"가맹점명: 오답매장{i}-{k} / 취급품목: 기타{i}-{k}" for k in range(4)],
            }, ensure_ascii=False) + "\n")
    TRAIN_META = None
else:
    TRAIN_PAIRS = DATA_DIR / "train_pairs.jsonl"
    TRAIN_META = json.loads((DATA_DIR / "train_pairs.meta.json").read_text(encoding="utf-8"))
    if TRAIN_META.get("train_pairs_sha256") != sha256_file(TRAIN_PAIRS):
        raise RuntimeError("train_pairs.jsonl과 meta.json이 맞지 않습니다 — pack_for_colab.py로 data/를 다시 올리세요.")

with TRAIN_PAIRS.open(encoding="utf-8") as f:
    RECORDS = [json.loads(line) for line in f if line.strip()]
print(f"[데이터] corpus {len(corpus):,}  queries {queries['split'].value_counts().to_dict()}  학습 query {len(RECORDS)}"
      + ("  (SMOKE: 가짜 학습 데이터·축소 코퍼스)" if SMOKE else f"  qrels={TRAIN_META.get('qrels_kind')}"))

# ---- cell ----
# @cell rows
def expand_training_rows(records, num_hard_negatives, max_positives_per_query):
    rows, n_skipped, n_used = [], 0, 0
    for record in records:
        positives = record.get("positives")
        if positives is None:
            positives = [record["positive"]]
        if max_positives_per_query is not None:
            positives = positives[:max_positives_per_query]   # relevance 높은 순으로 정렬돼 있음
        negatives = record["negatives"][:num_hard_negatives]
        if len(negatives) < num_hard_negatives:
            n_skipped += 1
            continue
        n_used += 1
        negative_columns = {f"negative_{i + 1}": text for i, text in enumerate(negatives)}
        for positive in positives:
            rows.append({"anchor": record["query"], "positive": positive, **negative_columns})
    stats = {"n_queries_in_file": len(records), "n_queries_used": n_used, "n_skipped_few_negatives": n_skipped,
             "n_rows": len(rows)}
    return rows, stats

# ---- cell ----
def resolve_query_prompt(model, preset):
    """학습·평가·서빙이 같은 query prompt를 쓰게: preset의 query_prompt(문자열)가 있으면 모델 prompts에 기록한다."""
    prompt_name = preset.get("query_prompt_name")
    if preset.get("query_prompt"):
        prompt_name = prompt_name or "query"
        model.prompts[prompt_name] = preset["query_prompt"]
    if prompt_name and prompt_name not in model.prompts:
        raise ValueError(f"query_prompt_name={prompt_name!r}가 모델 prompts {list(model.prompts)}에 없습니다.")
    return prompt_name, (model.prompts[prompt_name] if prompt_name else None)


def build_model(preset, hp, device):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(preset["model_id"], device=device, model_kwargs=dtype_kwargs(getattr(torch, hp["base_dtype"])))
    model.max_seq_length = hp["max_seq_length"]
    if hp["lora_rank"] is not None:
        from peft import LoraConfig, TaskType, get_peft_model

        transformer = model[0]
        set_transformer_model(transformer, get_peft_model(transformer.auto_model, LoraConfig(
            task_type=TaskType.FEATURE_EXTRACTION, r=hp["lora_rank"], lora_alpha=hp["lora_alpha"],
            lora_dropout=hp["lora_dropout"], target_modules="all-linear")))
        # fp16 베이스에 붙은 LoRA 파라미터는 AMP가 unscale을 못 해 에러 → 학습되는 파라미터만 fp32로
        for param in transformer.auto_model.parameters():
            if param.requires_grad:
                param.data = param.data.float()
        transformer.auto_model.print_trainable_parameters()
    return model


def build_loss(model, preset, hp, device):
    from sentence_transformers import SentenceTransformer

    losses = losses_module()
    guide = None
    # GradCache: batch 전체 임베딩은 grad 없이 먼저 구하고, 역전파는 mini_batch_size씩 나눠서 한다.
    # in-batch negative·loss·gradient는 일반 loss와 같고(드롭아웃 난수만 다름) GPU 메모리만 줄어든다.
    cached = bool(hp.get("mini_batch_size")) and hp["mini_batch_size"] < hp["batch_size"]
    mini = {"mini_batch_size": hp["mini_batch_size"]} if cached else {}
    if hp["loss"] == "gist":
        # guide(베이스 모델)가 정답보다 더 비슷하다고 보는 in-batch negative를 걸러 false negative를 줄인다
        guide = SentenceTransformer(preset["model_id"], device=device,
                                    model_kwargs=dtype_kwargs(torch.float16 if device == "cuda" else torch.float32))
        guide.max_seq_length = hp["max_seq_length"]
        guide.eval()
        loss = (losses.CachedGISTEmbedLoss if cached else losses.GISTEmbedLoss)(model, guide=guide, **mini)
    elif hp["loss"] == "mnrl":
        loss = (losses.CachedMultipleNegativesRankingLoss if cached else losses.MultipleNegativesRankingLoss)(model, **mini)
    else:
        raise ValueError(f"loss는 'gist' 또는 'mnrl': {hp['loss']!r}")
    target_dim, full_dim = preset.get("target_dimension"), embedding_dimension(model)
    if target_dim and target_dim < full_dim:
        # 평가·서빙은 앞 target_dim 차원만 쓰므로 그 차원에서도 성능이 유지되게 함께 학습
        loss = losses.MatryoshkaLoss(model, loss, matryoshka_dims=[full_dim, target_dim])
    print(f"[INFO] loss: {type(loss).__name__}" + (f"(mini_batch_size={hp['mini_batch_size']})" if cached else ""))
    return loss, guide

# ---- cell ----
# @cell runs
import gc
import math
import shutil
import time
from datetime import UTC, datetime

import yaml

KEEP_MARKER, PARTIAL, CKPT = "KEEP", ".partial", ".ckpt"
RESUME_IGNORED = {"note", "keep_last_runs", "save_mid_checkpoint", "resume_tag", "mini_batch_size"}


def run_prefix(base_name, owner):
    return f"{base_name}_ft_{owner}_"


def make_run_tag(base_name, owner, now=None):
    return f"{run_prefix(base_name, owner)}{(now or datetime.now(UTC)):%Y%m%d_%H%M}"


def latest_checkpoint(root):
    root = Path(root)
    found = [(int(m.group(1)), d) for d in (root.iterdir() if root.is_dir() else [])
             if d.is_dir() and (m := re.fullmatch(r"checkpoint-(\d+)", d.name))]
    return max(found)[1] if found else None


def prune_runs(run_root, prefix, keep_last):
    """같은 사람·같은 모델의 완성된 run 중 최신 keep_last개만 남긴다(KEEP 표시·.partial·.ckpt·manifest 없는 폴더는 안 건드림)."""
    def created(d):
        return json.loads((d / "model_manifest.json").read_text(encoding="utf-8")).get("created_at", "")

    runs = [d for d in Path(run_root).iterdir()
            if d.is_dir() and d.name.startswith(prefix) and not d.name.endswith(PARTIAL)
            and (d / "model_manifest.json").exists() and not (d / KEEP_MARKER).exists()]
    runs.sort(key=lambda d: (created(d), d.name), reverse=True)
    for d in runs[keep_last:]:
        shutil.rmtree(d)
        print(f"[정리] 오래된 run 삭제: {d.name}")


def notebook_code_snapshot():
    """지금 세션에서 실행한 셀 코드 전부(= 이 모델을 만든 코드). 모델 폴더에 notebook_code.py로 저장한다."""
    try:
        executed = get_ipython().user_ns.get("In", [])
    except NameError:
        executed = []
    return "\n\n# ---- cell ----\n".join(cell for cell in executed if cell)

# ---- cell ----
def train_model(preset, hp, owner, note, resume_tag=None, save_mid_checkpoint=True):
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
    )
    from transformers import TrainerCallback, set_seed

    set_seed(hp["seed"])
    base_name = preset["name"]
    tag = resume_tag.strip() if resume_tag else make_run_tag(base_name, owner)
    if not tag.startswith(run_prefix(base_name, owner)):
        raise ValueError(f"RESUME_TAG는 {run_prefix(base_name, owner)}로 시작해야 합니다(MODEL/OWNER가 처음과 같은지 확인)")
    FINETUNE_DIR.mkdir(parents=True, exist_ok=True)
    final_dir, partial_dir, ckpt_root = FINETUNE_DIR / tag, FINETUNE_DIR / f"{tag}{PARTIAL}", FINETUNE_DIR / f"{tag}{CKPT}"
    if final_dir.exists():
        raise SystemExit(f"{final_dir}가 이미 있습니다(이미 끝난 run이거나 1분 안에 다시 실행).")
    if partial_dir.exists():
        shutil.rmtree(partial_dir)

    run_config = {**hp, "model": preset["model_id"], "train_pairs_sha256": sha256_file(TRAIN_PAIRS)}
    resume_from = None
    if resume_tag:
        resume_from = latest_checkpoint(ckpt_root)
        if resume_from is None:
            raise SystemExit(f"{ckpt_root}에 체크포인트가 없습니다 — 처음부터 다시 돌리세요.")
        saved = json.loads((ckpt_root / "run_config.json").read_text(encoding="utf-8"))
        diff = sorted(k for k in set(saved) | set(run_config) if k not in RESUME_IGNORED and saved.get(k) != run_config.get(k))
        if diff:
            raise SystemExit(f"처음 실행과 설정/데이터가 다릅니다 — 처음 값으로 되돌리세요: {diff}")
        print(f"[INFO] 이어서 학습: {resume_from}")
    elif save_mid_checkpoint:
        ckpt_root.mkdir()
        (ckpt_root / "run_config.json").write_text(json.dumps(run_config, ensure_ascii=False, indent=2), encoding="utf-8")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    gc.collect()
    if device == "cuda":
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    precision = "bf16" if device == "cuda" and torch.cuda.is_bf16_supported() else ("fp16" if device == "cuda" else "fp32")
    print(f"[INFO] run: {tag}  base: {preset['model_id']}  precision: {precision}")

    rows, expand_stats = expand_training_rows(RECORDS, hp["num_hard_negatives"], hp["max_positives_per_query"])
    print(f"[INFO] 학습 데이터: {expand_stats}")
    model = build_model(preset, hp, device)
    prompt_name, query_prompt = resolve_query_prompt(model, preset)
    print(f"[INFO] query prompt ({prompt_name}): {query_prompt!r}")
    loss, guide = build_loss(model, preset, hp, device)

    non_finite, mid_steps = [], []

    class Guard(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            value = (logs or {}).get("loss")
            if value is not None and not math.isfinite(value):
                non_finite.append(state.global_step)
                control.should_training_stop = True

    class SaveOnceAtMidpoint(TrainerCallback):
        def on_step_end(self, args, state, control, **kwargs):
            if state.global_step == max(1, state.max_steps // 2):
                mid_steps.append(state.global_step)
                control.should_save = True

        def on_save(self, args, state, control, **kwargs):
            print(f"\n[체크포인트] step {state.global_step}/{state.max_steps} 저장 완료 — 끊기면 RESUME_TAG=\"{tag}\"")

    lora = hp["lora_rank"] is not None

    class Trainer(SentenceTransformerTrainer):
        def _load_from_checkpoint(self, checkpoint_path, model=None):
            if not lora:
                return super()._load_from_checkpoint(checkpoint_path)
            from peft import set_peft_model_state_dict
            from safetensors.torch import load_file

            state = load_file(str(Path(checkpoint_path) / "adapter_model.safetensors"))
            result = set_peft_model_state_dict(self.model[0].auto_model, state)
            if not state or result.unexpected_keys:
                raise RuntimeError(f"LoRA 체크포인트를 읽지 못했습니다: {checkpoint_path}")

    use_ckpt = save_mid_checkpoint or resume_from is not None
    args = SentenceTransformerTrainingArguments(
        output_dir=str(ckpt_root if use_ckpt else WORK_DIR / tag),
        num_train_epochs=hp["num_epochs"],
        per_device_train_batch_size=hp["batch_size"],
        learning_rate=hp["learning_rate"],
        **warmup_kwargs(SentenceTransformerTrainingArguments, hp["warmup_ratio"]),
        weight_decay=hp["weight_decay"],
        fp16=precision == "fp16",
        bf16=precision == "bf16",
        batch_sampler=batch_samplers().NO_DUPLICATES,   # 같은 텍스트가 한 배치에 두 번 안 들어가게
        prompts={"anchor": query_prompt} if query_prompt else None,
        save_strategy="no",
        save_total_limit=1,
        eval_strategy="no",
        logging_steps=10,
        report_to="none",
        seed=hp["seed"],
        data_seed=hp["seed"],
    )
    callbacks = [Guard()] + ([SaveOnceAtMidpoint()] if save_mid_checkpoint else [])
    trainer = Trainer(model=model, args=args, train_dataset=Dataset.from_list(rows), loss=loss, callbacks=callbacks)
    started = time.time()
    trainer.train(resume_from_checkpoint=str(resume_from) if resume_from else None)
    runtime_sec = round(time.time() - started, 1)
    peak_gb = round(torch.cuda.max_memory_allocated() / 2**30, 2) if device == "cuda" else None
    print(f"[INFO] 학습 시간 {runtime_sec}s, GPU 최대 사용 {peak_gb}GB")
    if non_finite:
        raise RuntimeError(f"step {non_finite[0]}에서 loss가 NaN/inf — 저장 안 함. lr을 낮추거나 bf16 GPU(L4/A100)를 쓰세요.")
    loss_history = [{"step": log["step"], "loss": round(log["loss"], 5)} for log in trainer.state.log_history if "loss" in log]
    global_steps = trainer.state.global_step
    del trainer, loss, guide
    gc.collect()
    torch.cuda.empty_cache()

    # ---- 저장: partial → 재로드 검증 → manifest → 최종 이름 ----
    # fp16/bf16 학습이면 accelerate가 모델 forward에 autocast를 씌워 두고 학습 뒤에도 남겨 둔다 → 벗겨야 저장본과 같은 조건으로 비교된다
    from accelerate.utils import extract_model_from_parallel

    model = extract_model_from_parallel(model, keep_fp32_wrapper=False)
    if lora:
        set_transformer_model(model[0], model[0].auto_model.merge_and_unload())
    saved_dtype = save_verified(model, partial_dir, prompt_name, device, hp["save_dtype"])

    target_dim, full_dim = preset.get("target_dimension"), embedding_dimension(model)
    eval_config = {"name": tag, "model_id": f"models/{tag}", "query_prompt_name": prompt_name,
                   "normalize_embeddings": preset.get("normalize_embeddings", True), "target_dimension": target_dim,
                   "batch_size": preset.get("batch_size", 32)}
    if preset.get("torch_dtype"):
        eval_config["torch_dtype"] = preset["torch_dtype"]
    (partial_dir / "eval_config.yaml").write_text(yaml.safe_dump(eval_config, allow_unicode=True, sort_keys=False),
                                                 encoding="utf-8")
    snapshot = notebook_code_snapshot()
    (partial_dir / "notebook_code.py").write_text(snapshot, encoding="utf-8")
    manifest = {
        "tag": tag, "owner": owner, "base_model_id": preset["model_id"], "base_model_config": preset,
        "framework": "sentence-transformers" + ("+peft-lora(merged)" if lora else ""),
        "hyperparameters": {**hp, "note": note, "resume_tag": resume_tag, "save_mid_checkpoint": save_mid_checkpoint},
        "precision": precision,
        "training_data": {"source": str(TRAIN_PAIRS), "sha256": sha256_file(TRAIN_PAIRS), "expansion": expand_stats,
                          "prepare_meta": TRAIN_META, "smoke": SMOKE},
        "data_version": DATA_VERSION,
        "code": {"notebook": "colab/train_eval.ipynb", "snapshot": "notebook_code.py",
                 "snapshot_sha256": hashlib.sha256(snapshot.encode("utf-8")).hexdigest()},
        "training_result": {"runtime_sec": runtime_sec, "resumed_from": resume_from.name if resume_from else None,
                            "mid_checkpoint_step": mid_steps[0] if mid_steps else None, "global_steps": global_steps, "peak_gpu_memory_gb": peak_gb,
                            "final_loss": loss_history[-1]["loss"] if loss_history else None, "loss_history": loss_history},
        "serving": {"document_template": (TRAIN_META or {}).get("template", "t1_minimal"), "query_prompt_name": prompt_name,
                    "query_prompt": model.prompts.get(prompt_name) if prompt_name else None, "document_prompt": None,
                    "embedding_dim": target_dim or full_dim, "full_embedding_dim": full_dim,
                    "normalize_embeddings": eval_config["normalize_embeddings"], "similarity": "cosine",
                    "max_seq_length": hp["max_seq_length"], "saved_dtype": saved_dtype},
        "environment": {"packages": library_versions(), "gpu": torch.cuda.get_device_name(0) if device == "cuda" else None},
        "created_at": datetime.now(UTC).isoformat(),
        "evaluations": [],
    }
    (partial_dir / "model_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    partial_dir.rename(final_dir)
    print(f"[완료] 최종 모델: {final_dir}")
    if ckpt_root.exists():
        shutil.rmtree(ckpt_root)
    prune_runs(FINETUNE_DIR, run_prefix(base_name, owner), hp["keep_last_runs"])
    return final_dir


VERIFY_TEXTS = [(["국밥", "24시 약국", "아이 옷 가게"], True),
                (["가맹점명: 할매순대국 / 취급품목: 한식", "가맹점명: 온누리약국 / 취급품목: 의약품"], False)]


def _verify_embeddings(model, prompt_name):
    return [model.encode(texts, normalize_embeddings=True, convert_to_tensor=True,
                         **({"prompt_name": prompt_name} if use_prompt and prompt_name else {})).float().cpu()
            for texts, use_prompt in VERIFY_TEXTS]


def save_verified(model, saved_dir, prompt_name, device, save_dtype):
    """저장본을 다시 불러와 학습된 모델과 같은 임베딩이 나오는지 확인(pooling·prompt 누락, 저장 dtype 문제 방지).

    기준은 학습된 그대로(저장 dtype으로 바꾸기 전)의 임베딩이다. save_dtype(기본 float16)으로 저장했을 때 달라지면
    float32로 다시 저장한다(용량 2배지만 서비스에 쓸 수 있는 모델이 남는다). 반환값: 실제로 저장한 dtype.
    """
    from sentence_transformers import SentenceTransformer

    expected = _verify_embeddings(model, prompt_name)
    model.to("cpu")   # 재로드할 GPU 메모리 확보(4B)
    torch.cuda.empty_cache()
    for dtype in dict.fromkeys([save_dtype, "float32"]):
        if saved_dir.exists():
            shutil.rmtree(saved_dir)
        model.to(getattr(torch, dtype))
        model.save(str(saved_dir), safe_serialization=True)
        reloaded = SentenceTransformer(str(saved_dir), device=device, model_kwargs=dtype_kwargs(getattr(torch, dtype)))
        got = _verify_embeddings(reloaded, prompt_name)
        del reloaded
        gc.collect()
        torch.cuda.empty_cache()
        cosine = min(torch.nan_to_num(torch.nn.functional.cosine_similarity(a, b), nan=-1.0).min().item()
                     for a, b in zip(expected, got))
        if cosine >= 0.999:
            print(f"[검증] 저장본({dtype}) 재로드 임베딩 일치 확인 (최소 cosine {cosine:.5f})")
            return dtype
        print(f"[경고] {dtype}로 저장한 모델의 임베딩이 학습된 모델과 다릅니다(최소 cosine {cosine:.5f})"
              + (" — float32로 다시 저장합니다." if dtype != "float32" else ""))
    raise RuntimeError(f"저장본을 다시 불러오니 임베딩이 다릅니다 — {saved_dir}는 쓰면 안 됩니다. 출력 전체를 공유해 주세요.")

# ---- cell ----
# @cell eval
import ast

if not hasattr(ast, "Num"):   # ir_measures 0.4.3이 Python 3.12에서 사라진 ast.Num을 씀 — 그 함수 하나만 보정
    import ir_measures.util as _ir_util

    def _ast_to_value_compat(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Dict):
            return dict(zip(map(_ast_to_value_compat, node.keys), map(_ast_to_value_compat, node.values)))
        raise ValueError("values must be str, float, int, bool, etc.")

    _ir_util._ast_to_value = _ast_to_value_compat
import ir_measures

METRIC_SPECS = {"nDCG@10": "nDCG@10", "Precision@10": "P(rel=2)@10", "MRR@100": "RR(rel=2)@100",
                "Recall@50": "R(rel=2)@50", "Recall@100": "R(rel=2)@100", "Bpref": "Bpref(rel=2)",
                "Judged@10": "Judged@10", "Judged@100": "Judged@100"}
TEMPLATE_COLUMNS = {"t1_minimal": "search_text_t1_minimal", "t2_market": "search_text_t2_market",
                    "t3_market_type": "search_text_t3_market_type"}


def load_qrels(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return list(ir_measures.read_trec_qrels(f))


def load_run_csv(path):
    df = pd.read_csv(path, encoding="utf-8-sig")
    return [ir_measures.ScoredDoc(str(r.query_id), str(r.doc_id), float(r.score)) for r in df.itertuples(index=False)]


def calculate_metrics(qrels, run):
    measures = [ir_measures.parse_measure(spec) for spec in METRIC_SPECS.values()]
    aggregate = ir_measures.calc_aggregate(measures, qrels, run)
    names = {str(ir_measures.parse_measure(spec)): name for name, spec in METRIC_SPECS.items()}
    rows = [{"query_id": str(r.query_id), "metric": names.get(str(r.measure), str(r.measure)), "value": float(r.value)}
            for r in ir_measures.iter_calc(measures, qrels, run)]
    per_query = pd.DataFrame(rows).pivot(index="query_id", columns="metric", values="value").reset_index()
    by_name = {str(k): float(v) for k, v in aggregate.items()}
    return {name: by_name[str(ir_measures.parse_measure(spec))] for name, spec in METRIC_SPECS.items()
            if str(ir_measures.parse_measure(spec)) in by_name}, per_query


def bootstrap_ci(values, samples, seed):
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [None, None]
    means = x[np.random.default_rng(seed).integers(0, len(x), size=(samples, len(x)))].mean(axis=1)
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def paired_permutation_pvalue(diffs, samples, seed):
    d = np.asarray(diffs, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return None
    observed = abs(float(d.mean()))
    signs = np.random.default_rng(seed).choice(np.array([-1.0, 1.0]), size=(samples, len(d)))
    return float((np.sum(np.abs((signs * d).mean(axis=1)) >= observed) + 1) / (samples + 1))


def compare_runs(new_pq, base_pq, samples, seed):
    merged = new_pq.merge(base_pq, on="query_id", suffixes=("_new", "_base"), how="inner")
    out = {}
    for metric in METRIC_SPECS:
        if f"{metric}_new" not in merged or f"{metric}_base" not in merged:
            continue
        diffs = merged[f"{metric}_new"].to_numpy() - merged[f"{metric}_base"].to_numpy()
        diffs = diffs[np.isfinite(diffs)]
        if len(diffs):
            out[metric] = {"delta_mean": float(diffs.mean()), "delta_ci95": bootstrap_ci(diffs, samples, seed),
                           "paired_permutation_pvalue": paired_permutation_pvalue(diffs, samples, seed + 1),
                           "wins": int((diffs > 0).sum()), "ties": int((diffs == 0).sum()), "losses": int((diffs < 0).sum())}
    return out


def validate_run(df, expected_query_ids):
    actual = set(df["query_id"].astype(str))
    return {"rows": len(df), "queries": int(df["query_id"].nunique()), "expected_queries": len(expected_query_ids),
            "missing_queries": len(expected_query_ids - actual), "unknown_queries": len(actual - expected_query_ids),
            "duplicate_query_doc_pairs": int(df.duplicated(["query_id", "doc_id"]).sum()),
            "invalid_rank_rows": int((pd.to_numeric(df["rank"], errors="coerce") <= 0).sum())}


def score_run(run_path, qrels_path, tag, samples, seed, baseline_run_path=None, baseline_tag="baseline"):
    """run.csv 하나를 채점한 report(dict)와 쿼리별 지표를 돌려준다(공식 evaluator와 같은 형식)."""
    qrels, run = load_qrels(qrels_path), load_run_csv(run_path)
    aggregate, per_query = calculate_metrics(qrels, run)
    expected = {str(q.query_id) for q in qrels}
    ci = {m: {"mean": float(np.nanmean(per_query[m].to_numpy())), "ci95": bootstrap_ci(per_query[m].to_numpy(), samples, seed)}
          for m in METRIC_SPECS if m in per_query.columns}
    report = {"benchmark": "StoreSearch-KO v1", "tag": tag, "qrels": str(qrels_path), "run": str(run_path),
              "primary_metric": "nDCG@10", "binary_relevance_threshold": 2, "metrics": list(METRIC_SPECS),
              "query_count": len(expected), "run_query_count": int(per_query["query_id"].nunique()),
              "aggregate": aggregate, "query_bootstrap_ci95": ci,
              "run_validation": validate_run(pd.read_csv(run_path, encoding="utf-8-sig"), expected)}
    if baseline_run_path is not None:
        base_aggregate, base_pq = calculate_metrics(load_qrels(qrels_path), load_run_csv(baseline_run_path))
        report["comparison"] = {"baseline_tag": baseline_tag, "baseline_run": str(baseline_run_path),
                                "baseline_aggregate": base_aggregate,
                                "metrics": compare_runs(per_query, base_pq, samples, seed)}
    return report, per_query


def exact_search(query_emb, doc_emb, query_ids, doc_ids, top_k, system):
    scores = query_emb.astype("float32") @ doc_emb.astype("float32").T
    top_k, rows = min(top_k, len(doc_ids)), []
    for i, qid in enumerate(query_ids):
        idx = np.argpartition(-scores[i], top_k - 1)[:top_k]
        idx = idx[np.argsort(-scores[i][idx])]
        rows += [{"query_id": qid, "doc_id": doc_ids[j], "rank": r, "score": float(scores[i][j]), "system": system}
                 for r, j in enumerate(idx, start=1)]
    return pd.DataFrame(rows, columns=["query_id", "doc_id", "rank", "score", "system"])


def load_encoder(cfg):
    from sentence_transformers import SentenceTransformer

    kwargs = dtype_kwargs(getattr(torch, cfg["torch_dtype"])) if cfg.get("torch_dtype") else None
    return SentenceTransformer(str(cfg["model_id"]), device="cuda" if torch.cuda.is_available() else "cpu",
                               model_kwargs=kwargs)


def encode(model, texts, cfg, is_query):
    kwargs = {"batch_size": cfg.get("batch_size", 32), "normalize_embeddings": False, "show_progress_bar": True,
              "convert_to_numpy": True}
    if is_query and cfg.get("query_prompt"):
        kwargs["prompt"] = cfg["query_prompt"]
    elif is_query and cfg.get("query_prompt_name"):
        kwargs["prompt_name"] = cfg["query_prompt_name"]
    with torch.no_grad():
        emb = model.encode(texts, **kwargs)
    if cfg.get("target_dimension"):
        emb = emb[:, : cfg["target_dimension"]]
    if cfg.get("normalize_embeddings", True):
        emb = emb / np.clip(np.linalg.norm(emb, axis=1, keepdims=True), 1e-12, None)
    return emb.astype("float32")


def evaluate(cfg, split="val", template="t1_minimal", baseline_tag=None, allow_test=False, model=None,
             doc_embeddings=None, top_k=100):
    """모델(cfg) 하나를 split으로 평가: 인코딩 → exact 검색 → 채점 → Drive 저장 → (fine-tuned면) manifest에 기록."""
    if split == "test" and not allow_test:
        raise ValueError("test split은 최종 후보를 정한 뒤 한 번만 봅니다 — 최종 평가면 allow_test=True.")
    tag = cfg["name"]
    model = model or load_encoder(cfg)
    split_q = queries[queries["split"] == split].reset_index(drop=True)
    if doc_embeddings is None:
        doc_embeddings = encode(model, corpus[TEMPLATE_COLUMNS[template]].fillna("").astype(str).tolist(), cfg, False)
    query_emb = encode(model, split_q["query"].astype(str).tolist(), cfg, True)
    run = exact_search(query_emb, doc_embeddings, split_q["query_id"].tolist(), corpus["doc_id"].tolist(), top_k,
                       f"{tag}_{template}")
    run_path = RUN_DIR / tag / f"run_{template}_{split}.csv"
    run_path.parent.mkdir(parents=True, exist_ok=True)
    run.to_csv(run_path, index=False, encoding="utf-8-sig", lineterminator="\n")

    baseline_run = RUN_DIR / baseline_tag / run_path.name if baseline_tag and baseline_tag != tag else None
    if baseline_run is not None and not baseline_run.exists():
        print(f"[안내] 기준 모델 run이 없어 비교를 건너뜀: {baseline_run}")
        baseline_run = None
    etag = f"{tag}_{template}_{split}"
    report, per_query = score_run(run_path, QRELS[split], etag, int(EVAL_SETTINGS["bootstrap_samples"]),
                                  int(EVAL_SETTINGS["random_seed"]), baseline_run, baseline_tag or "baseline")
    report.update({"official": OFFICIAL, "corpus_docs": len(corpus), "model_id": str(cfg["model_id"]),
                   "evaluated_at": datetime.now(UTC).isoformat(), "library_versions": library_versions(),
                   "evaluated_with": "colab/train_eval.ipynb"})
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    per_query.to_csv(EVAL_DIR / f"{etag}_per_query.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (EVAL_DIR / f"{etag}_evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest_path = Path(str(cfg["model_id"])) / "model_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest.setdefault("evaluations", []).append(
            {"evaluated_at": report["evaluated_at"], "split": split, "template": template, "tag": etag,
             "official": OFFICIAL, "metrics": report["aggregate"], "baseline": baseline_tag, "where": "colab"})
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report": report, "model": model, "doc_embeddings": doc_embeddings, "run_path": run_path}


def format_report(report, metrics=("nDCG@10", "Judged@10", "Recall@100", "MRR@100")):
    lines = [f"[{report['tag']}] queries={report['query_count']} corpus={report.get('corpus_docs')}"
             + ("" if report.get("official", True) else "  (비공식)")]
    for m in metrics:
        value, ci = report["aggregate"].get(m), report["query_bootstrap_ci95"].get(m, {}).get("ci95")
        if value is not None:
            lines.append(f"  {m:<11} {value:.4f}" + (f"  [95% CI {ci[0]:.4f}, {ci[1]:.4f}]" if ci and ci[0] is not None else ""))
    if report.get("comparison"):
        lines.append(f"  vs {report['comparison']['baseline_tag']}:")
        for m in metrics:
            r = report["comparison"]["metrics"].get(m)
            if r:
                lines.append(f"    {m:<11} Δ={r['delta_mean']:+.4f}  p={r['paired_permutation_pvalue']:.4f}  "
                             f"wins/ties/losses={r['wins']}/{r['ties']}/{r['losses']}")
    return "\n".join(lines)


def leaderboard(split="val", include_unofficial=False):
    rows = []
    for path in sorted(EVAL_DIR.glob(f"*_{split}_evaluation.json")):
        report = json.loads(path.read_text(encoding="utf-8"))
        if not include_unofficial and not report.get("official", True):
            continue
        row = {"tag": report["tag"], **{m: report["aggregate"].get(m) for m in METRIC_SPECS}}
        if report.get("comparison"):
            ndcg = report["comparison"]["metrics"].get("nDCG@10", {})
            row.update({"ΔnDCG@10": ndcg.get("delta_mean"), "p(nDCG@10)": ndcg.get("paired_permutation_pvalue")})
        libs = report.get("library_versions") or {}
        row["libs"] = f"st{libs.get('sentence-transformers')}/tf{libs.get('transformers')}" if libs else None
        rows.append(row)
    return pd.DataFrame(rows).sort_values("nDCG@10", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def release_gpu():
    """호출한 쪽에서 모델·임베딩 변수를 None으로 지운 뒤 부른다(남은 참조가 없어야 GPU 메모리가 풀린다)."""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

# ---- cell ----
if not EVAL_RUN_TAG:
    final_dir = train_model(preset, HP, OWNER, NOTE, resume_tag=RESUME_TAG, save_mid_checkpoint=SAVE_MID_CHECKPOINT)

# ---- cell ----
base_cfg = {k: v for k, v in preset.items() if k != "train"}
if not (RUN_DIR / base_cfg["name"] / "run_t1_minimal_val.csv").exists():
    print(f"[기준 모델] {base_cfg['name']} zero-shot 평가(처음 한 번)")
    baseline = evaluate(base_cfg)
    print(format_report(baseline["report"]))
    baseline = None
    release_gpu()

if not EVAL_RUN_TAG and "final_dir" not in globals():
    raise SystemExit("8. 학습이 끝나지 않았습니다(중단·오류). 다시 학습하거나, 끝난 run을 평가하려면 EVAL_RUN_TAG에 TAG를 넣으세요.")
run_dir = FINETUNE_DIR / EVAL_RUN_TAG if EVAL_RUN_TAG else final_dir
eval_cfg = {**yaml.safe_load((run_dir / "eval_config.yaml").read_text(encoding="utf-8")), "model_id": str(run_dir)}
result = evaluate(eval_cfg, baseline_tag=base_cfg["name"])
print(format_report(result["report"]))
result = None
release_gpu()

# ---- cell ----
board = leaderboard("val", include_unofficial=SMOKE)
cols = ["tag", "nDCG@10", "ΔnDCG@10", "p(nDCG@10)", "Judged@10", "Recall@100", "MRR@100", "libs"]
print(board[[c for c in cols if c in board.columns]].to_string(index=False) if len(board) else "(평가 없음)")

# ---- cell ----
ZERO_SHOT_MODELS = []      # 예: ["arctic_ko", "arctic_ko_query", "bge_m3", "qwen3_0_6b", "qwen3_0_6b_store"]
BASELINE_FOR_TABLE = None  # 예: "qwen3_embedding_0_6b" — 주면 각 모델의 Δ·p 계산

model, doc_emb, last_key = None, None, None
for key in ZERO_SHOT_MODELS:
    cfg = {k: v for k, v in MODEL_PRESETS[key].items() if k != "train"}
    if (RUN_DIR / cfg["name"] / "run_t1_minimal_val.csv").exists():
        print(f"{cfg['name']}: 이미 평가됨 — 건너뜀")
        continue
    same_docs = (cfg["model_id"], cfg.get("torch_dtype"), cfg.get("target_dimension"))
    if same_docs != last_key:
        model, doc_emb = None, None
        release_gpu()
    out = evaluate(cfg, baseline_tag=BASELINE_FOR_TABLE, model=model, doc_embeddings=doc_emb)
    model, doc_emb, last_key = out["model"], out["doc_embeddings"], same_docs
    print(format_report(out["report"]))
    out = None   # 다음 모델로 넘어갈 때 이전 모델이 GPU에서 풀리도록 참조를 남기지 않는다
model = doc_emb = out = None
release_gpu()

# ---- cell ----
if SMOKE:
    if "final_dir" not in globals():
        raise SystemExit("8. 학습이 끝나지 않았습니다 — SMOKE는 8번부터 다시 실행하세요.")
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")

    files = {p.name for p in final_dir.iterdir()}
    check("모델 폴더에 manifest·eval_config·코드 사본·ST 설정", {"model_manifest.json", "eval_config.yaml", "notebook_code.py",
          "modules.json", "config_sentence_transformers.json"} <= files, sorted(files))
    check("LoRA는 merge된 전체 모델로 저장", "adapter_config.json" not in files)
    check("중간 체크포인트·partial 폴더 정리됨", not (FINETUNE_DIR / f"{final_dir.name}{CKPT}").exists()
          and not (FINETUNE_DIR / f"{final_dir.name}{PARTIAL}").exists())
    manifest = json.loads((final_dir / "model_manifest.json").read_text(encoding="utf-8"))
    tr = manifest["training_result"]
    check("중간 체크포인트가 저장됐었음(또는 이어서 학습)", tr["mid_checkpoint_step"] is not None or tr["resumed_from"] is not None)
    check("loss 유한", all(math.isfinite(h["loss"]) for h in tr["loss_history"]), f"final={tr['final_loss']}")
    evaluations = [e for e in manifest["evaluations"] if e["split"] == "val"]
    check("평가가 manifest에 기록됨", bool(evaluations))
    report = json.loads((EVAL_DIR / f"{final_dir.name}_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    v = report["run_validation"]
    check("val 쿼리 전부 채점(누락·중복 0)", v["missing_queries"] == 0 and v["duplicate_query_doc_pairs"] == 0)
    check("기준 모델 대비 비교 계산", "comparison" in report)
    check("리더보드에 기준·학습 모델", len(leaderboard("val", include_unofficial=True)) >= 2)
    check("비공식 평가는 기본 리더보드에서 빠짐", leaderboard("val").empty)
    try:
        evaluate(eval_cfg, split="test")
        check("test는 allow_test 없이 차단", False)
    except ValueError:
        check("test는 allow_test 없이 차단", True)
    print("\n통과" if all(checks) else "\n실패 항목이 있습니다 — 출력 전체를 공유해 주세요")
    print(f"확인이 끝나면 Drive {RUNS} 폴더는 지워도 됩니다.")

# ---- cell ----
ZERO_SHOT_MODELS = []      # 예: ["arctic_ko", "arctic_ko_query", "bge_m3", "qwen3_0_6b", "qwen3_0_6b_store"]
BASELINE_FOR_TABLE = None  # 예: "qwen3_embedding_0_6b" — 주면 각 모델의 Δ·p 계산

model, doc_emb, last_key = None, None, None
for key in ZERO_SHOT_MODELS:
    cfg = {k: v for k, v in MODEL_PRESETS[key].items() if k != "train"}
    if (RUN_DIR / cfg["name"] / "run_t1_minimal_val.csv").exists():
        print(f"{cfg['name']}: 이미 평가됨 — 건너뜀")
        continue
    same_docs = (cfg["model_id"], cfg.get("torch_dtype"), cfg.get("target_dimension"))
    if same_docs != last_key:
        model, doc_emb = None, None
        release_gpu()
    out = evaluate(cfg, baseline_tag=BASELINE_FOR_TABLE, model=model, doc_embeddings=doc_emb)
    model, doc_emb, last_key = out["model"], out["doc_embeddings"], same_docs
    print(format_report(out["report"]))
    out = None   # 다음 모델로 넘어갈 때 이전 모델이 GPU에서 풀리도록 참조를 남기지 않는다
model = doc_emb = out = None
release_gpu()

# ---- cell ----
if SMOKE:
    if "final_dir" not in globals():
        raise SystemExit("8. 학습이 끝나지 않았습니다 — SMOKE는 8번부터 다시 실행하세요.")
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")

    files = {p.name for p in final_dir.iterdir()}
    check("모델 폴더에 manifest·eval_config·코드 사본·ST 설정", {"model_manifest.json", "eval_config.yaml", "notebook_code.py",
          "modules.json", "config_sentence_transformers.json"} <= files, sorted(files))
    check("LoRA는 merge된 전체 모델로 저장", "adapter_config.json" not in files)
    check("중간 체크포인트·partial 폴더 정리됨", not (FINETUNE_DIR / f"{final_dir.name}{CKPT}").exists()
          and not (FINETUNE_DIR / f"{final_dir.name}{PARTIAL}").exists())
    manifest = json.loads((final_dir / "model_manifest.json").read_text(encoding="utf-8"))
    tr = manifest["training_result"]
    check("중간 체크포인트가 저장됐었음(또는 이어서 학습)", tr["mid_checkpoint_step"] is not None or tr["resumed_from"] is not None)
    check("loss 유한", all(math.isfinite(h["loss"]) for h in tr["loss_history"]), f"final={tr['final_loss']}")
    evaluations = [e for e in manifest["evaluations"] if e["split"] == "val"]
    check("평가가 manifest에 기록됨", bool(evaluations))
    report = json.loads((EVAL_DIR / f"{final_dir.name}_t1_minimal_val_evaluation.json").read_text(encoding="utf-8"))
    v = report["run_validation"]
    check("val 쿼리 전부 채점(누락·중복 0)", v["missing_queries"] == 0 and v["duplicate_query_doc_pairs"] == 0)
    check("기준 모델 대비 비교 계산", "comparison" in report)
    check("리더보드에 기준·학습 모델", len(leaderboard("val", include_unofficial=True)) >= 2)
    check("비공식 평가는 기본 리더보드에서 빠짐", leaderboard("val").empty)
    try:
        evaluate(eval_cfg, split="test")
        check("test는 allow_test 없이 차단", False)
    except ValueError:
        check("test는 allow_test 없이 차단", True)
    print("\n통과" if all(checks) else "\n실패 항목이 있습니다 — 출력 전체를 공유해 주세요")
    print(f"확인이 끝나면 Drive {RUNS} 폴더는 지워도 됩니다.")

# ---- cell ----
# @cell settings
import re
from pathlib import Path

OWNER = "kse1"                 # 필수: 영문 소문자로 시작하는 2~16자(소문자·숫자), 예 "jisu"
MODEL = "qwen3_0_6b"       # MODEL_PRESETS의 키
NOTE = "baseline"                  # 기본값에서 바꾼 것 한 줄. 모델 밖 처리(쿼리 전처리 등)를 넣었으면 "서비스도 필요: ..."로 시작
SMOKE = False              # True: 가짜 학습 데이터 + 축소 코퍼스로 전체 흐름만 확인(결과는 runs_smoke/, 비공식)
RESUME_TAG = None          # Colab이 끊겨 이어서 학습할 때만: 로그의 [체크포인트] RESUME_TAG 값
SAVE_MID_CHECKPOINT = True # 학습 절반에서 한 번 Drive 저장(Arctic/BGE는 약 7GB, 끝나면 자동 삭제). 공간 없으면 False
EVAL_RUN_TAG = None        # 학습 없이 평가만: Drive runs/finetune/ 의 TAG
FINAL_TEST = False         # 팀이 최종 후보를 정한 뒤에만 True(test 채점)

STORE_PROMPT = ("Instruct: Given a Korean local-store search query, retrieve stores that satisfy the user's shopping, "
                "dining, or service intent\nQuery:")
MODEL_PRESETS = {
    # name: 결과 폴더/리더보드에 쓰는 이름(저장소 configs/models/*.yaml의 name과 같음)
    # train: 이 모델의 학습 기본값(LoRA 여부, lr, 베이스 dtype, batch, loss, mini_batch_size)
    "arctic_ko": {"name": "snowflake_arctic_embed_l_v2_ko", "model_id": "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
                      "query_prompt_name": None, "batch_size": 32,
                      "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "arctic_ko_query": {"name": "snowflake_arctic_embed_l_v2_ko_query", "model_id": "dragonkue/snowflake-arctic-embed-l-v2.0-ko",
                            "query_prompt_name": "query", "batch_size": 32,
                            "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "bge_m3": {"name": "bge_m3", "model_id": "BAAI/bge-m3", "query_prompt_name": None, "batch_size": 32,
                   "train": {"lora_rank": None, "learning_rate": 2e-5, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "qwen3_0_6b": {"name": "qwen3_embedding_0_6b", "model_id": "Qwen/Qwen3-Embedding-0.6B", "query_prompt_name": "query",
                       "batch_size": 32,
                       "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    "qwen3_0_6b_store": {"name": "qwen3_embedding_0_6b_store", "model_id": "Qwen/Qwen3-Embedding-0.6B",
                             "query_prompt": STORE_PROMPT, "batch_size": 32,
                             "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float32", "batch_size": 32, "loss": "gist", "mini_batch_size": 16}},
    # 4B: T4(15GB)면 fp16 베이스 + batch 8 + mnrl. 평가도 fp16으로 올리고 앞 1024차원만 쓴다(Matryoshka로 학습)
    "qwen3_4b": {"name": "qwen3_embedding_4b", "model_id": "Qwen/Qwen3-Embedding-4B", "query_prompt_name": "query",
                     "batch_size": 8, "target_dimension": 1024, "torch_dtype": "float16",
                     "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float16", "batch_size": 8, "loss": "mnrl", "mini_batch_size": 4}},
    "qwen3_4b_store": {"name": "qwen3_embedding_4b_store", "model_id": "Qwen/Qwen3-Embedding-4B", "query_prompt": STORE_PROMPT,
                           "batch_size": 8, "target_dimension": 1024, "torch_dtype": "float16",
                           "train": {"lora_rank": 16, "learning_rate": 1e-4, "base_dtype": "float16", "batch_size": 8, "loss": "mnrl", "mini_batch_size": 4}},
}

preset = MODEL_PRESETS[MODEL]
HP = {                       # 학습 설정 — 팀 공통 기본값(모델별 값은 preset["train"]에서)
    "num_epochs": 2,
    "batch_size": preset["train"]["batch_size"],   # 한 step의 in-batch negative 수(결과에 영향) — 팀 기준값 유지
    "mini_batch_size": preset["train"]["mini_batch_size"],  # GPU에 한 번에 올리는 문장 수(메모리만, 결과 동일). OOM이면 절반으로
    "learning_rate": preset["train"]["learning_rate"],
    "warmup_ratio": 0.1,
    "weight_decay": 0.01,
    "max_seq_length": 128,          # 문서 평균 24자 — 128이면 충분
    "num_hard_negatives": 3,        # 6 이하 권장(7 이상이면 negative가 적은 일부 쿼리가 빠짐)
    "max_positives_per_query": 32,
    "loss": preset["train"]["loss"],          # "gist"(같은 계열 쿼리끼리 정답을 오답으로 배우는 문제 완화) / "mnrl"
    "lora_rank": preset["train"]["lora_rank"],  # None이면 full fine-tuning
    "lora_alpha": 32,
    "lora_dropout": 0.05,
    "base_dtype": preset["train"]["base_dtype"],
    "save_dtype": "float16",        # Drive에 저장할 dtype(fp32의 절반 용량)
    "seed": 20260831,
    "keep_last_runs": 3,            # 내 run 중 같은 모델 최신 N개만 Drive에 남김(KEEP 파일 있는 run은 보존)
}

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
DATA_DIR = DRIVE_ROOT / "data"
RUNS = DRIVE_ROOT / ("runs_smoke" if SMOKE else "runs")
FINETUNE_DIR, RUN_DIR, EVAL_DIR = RUNS / "finetune", RUNS / "model_eval", RUNS / "evaluation"
WORK_DIR = Path("/content/ft_work")
OFFICIAL = not SMOKE

if SMOKE:
    OWNER = OWNER or "smoke"
if not re.fullmatch(r"[a-z][a-z0-9]{1,15}", OWNER):
    raise ValueError("OWNER를 영문 소문자로 시작하는 2~16자(소문자·숫자)로 적으세요, 예: 'jisu'")
print(f"[설정] MODEL={MODEL} ({preset['model_id']})  OWNER={OWNER}  SMOKE={SMOKE}  → {RUNS}")

# ---- cell ----
if not EVAL_RUN_TAG:
    final_dir = train_model(preset, HP, OWNER, NOTE, resume_tag=RESUME_TAG, save_mid_checkpoint=SAVE_MID_CHECKPOINT)

# ---- cell ----
import hashlib
import json

import numpy as np
import pandas as pd


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


DATA_VERSION = json.loads((DATA_DIR / "data_version.json").read_text(encoding="utf-8"))
EVAL_SETTINGS = DATA_VERSION["evaluation"]          # bootstrap 횟수·seed(저장소 configs/benchmark와 같은 값)
corpus = pd.read_parquet(DATA_DIR / DATA_VERSION["corpus_file"])
queries = pd.read_csv(DATA_DIR / "queries.csv", encoding="utf-8-sig")
queries = queries[queries["status"].astype(str).str.lower() == "active"].reset_index(drop=True)
QRELS = {split: DATA_DIR / f"qrels_{split}.trec" for split in ("val", "test")}

if SMOKE:
    judged = {line.split()[2] for line in QRELS["val"].read_text(encoding="utf-8").splitlines() if line.strip()}
    corpus = pd.concat([corpus[corpus["doc_id"].isin(judged)],
                        corpus[~corpus["doc_id"].isin(judged)].sample(2000, random_state=0)]).reset_index(drop=True)
    TRAIN_PAIRS = Path("/content/smoke_train_pairs.jsonl")
    with TRAIN_PAIRS.open("w", encoding="utf-8", newline="\n") as f:
        for i in range(40):   # query 40개 × positive 4개 = 160행(10 step) — 흐름 확인용이라 짧게, 텍스트는 전부 서로 다르게
            f.write(json.dumps({
                "query_id": f"smoke_{i}", "query": f"테스트 질의 {i}번 매장",
                "positives": [f"가맹점명: 정답매장{i}-{j} / 취급품목: 품목{i}" for j in range(4)],
                "negatives": [f"가맹점명: 오답매장{i}-{k} / 취급품목: 기타{i}-{k}" for k in range(4)],
            }, ensure_ascii=False) + "\n")
    TRAIN_META = None
else:
    TRAIN_PAIRS = DATA_DIR / "train_pairs.jsonl"
    TRAIN_META = json.loads((DATA_DIR / "train_pairs.meta.json").read_text(encoding="utf-8"))
    if TRAIN_META.get("train_pairs_sha256") != sha256_file(TRAIN_PAIRS):
        raise RuntimeError("train_pairs.jsonl과 meta.json이 맞지 않습니다 — pack_for_colab.py로 data/를 다시 올리세요.")

with TRAIN_PAIRS.open(encoding="utf-8") as f:
    RECORDS = [json.loads(line) for line in f if line.strip()]
print(f"[데이터] corpus {len(corpus):,}  queries {queries['split'].value_counts().to_dict()}  학습 query {len(RECORDS)}"
      + ("  (SMOKE: 가짜 학습 데이터·축소 코퍼스)" if SMOKE else f"  qrels={TRAIN_META.get('qrels_kind')}"))

# ---- cell ----
if not EVAL_RUN_TAG:
    final_dir = train_model(preset, HP, OWNER, NOTE, resume_tag=RESUME_TAG, save_mid_checkpoint=SAVE_MID_CHECKPOINT)