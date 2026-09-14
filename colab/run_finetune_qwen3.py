# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_qwen3.ipynb

Colab(무료 T4)에서 Qwen3-Embedding을 ms-swift로 LoRA fine-tuning한다.

**왜 ms-swift인가**: pyproject.toml에 `train = ["ms-swift"]`로 이미 선언돼 있었다(팀이 미리
정해둔 방향). ms-swift는 Qwen 계열(ModelScope/Alibaba)의 공식 학습 도구라 Qwen3-Embedding에
대한 지원이 가장 먼저/잘 들어온다. LoRA + 4bit 양자화(QLoRA)를 지원해서 무료 Colab GPU(T4,
~15GB) 메모리로도 4B/8B 모델까지 학습을 시도할 수 있다(0.6B는 LoRA만으로 충분, 4B/8B는
4bit 양자화를 같이 켜는 것을 권장).

**중요**: 아래 `swift sft` 커맨드의 플래그명은 ms-swift 공개 문서/embedding 학습 가이드 기준
best-effort로 작성한 것이다. ms-swift는 빠르게 바뀌는 라이브러리라서, **실행 전에 반드시**
Colab 셀에서 `!swift sft --help`와 `!swift sft --help_task embedding`(또는 설치된 버전의
embedding 학습 문서)로 실제 플래그명을 확인하고 아래 COMMAND를 맞게 고칠 것.

사용 전 준비 (한 번만):
  1. 로컬에서 `python scripts/prepare_finetune_dataset.py`로 data/finetune/train_pairs.jsonl 생성
  2. Drive에 아래 업로드:
       project/src/store_search_ai/   (model_manifest.json 기록용, 그대로 폴더째)
       project/data/finetune/train_pairs.jsonl
     (모델 자체는 model_id로 HF Hub에서 바로 받으므로 별도 업로드 불필요)
  3. 이 스크립트를 Colab에서 실행 — 학습이 끝나면 OUTPUT_DIR에 `model_manifest.json`도
     같이 저장된다(base 모델, 하이퍼파라미터, 학습 데이터 sha256 등 — 나중에 이 체크포인트가
     정확히 뭘로 학습된 건지 추적하기 위함. 서비스에 실제로 가져다 쓸 체크포인트라면 이 기록이
     없으면 재현/검증이 안 된다).
  4. 끝나면 Drive의 runs/finetune/<태그>/ 를 통째로 내려받아 로컬 models/ 밑에 둔다
     (model_manifest.json도 그 폴더 안에 같이 내려받아진다)
  5. configs/models/<태그>.yaml을 새로 만들어 model_id를 그 로컬 경로로 지정하고,
     scripts/14_run_model_eval.py --model-config configs/models/<태그>.yaml --split val 로 평가
     (fine-tuning 전용 평가 코드는 따로 없다 — 기존 zero-shot 평가 harness를 그대로 재사용한다.
      "run을 채점하는 evaluator는 하나만 둔다"는 docs/MODELING.md 원칙과 동일. 평가 결과는
      자동으로 model_manifest.json의 evaluations 목록에도 추가된다 — 14_run_model_eval.py 참고)
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")

get_ipython().system(
    'pip -q install -U "ms-swift" "transformers>=4.51.0" peft bitsandbytes accelerate'
)

from google.colab import drive

drive.mount("/content/drive")

import json
import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
PROJECT_DIR = DRIVE_ROOT / "project"
FINETUNE_RUN_DIR = DRIVE_ROOT / "runs" / "finetune"
FINETUNE_RUN_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_DIR / "src"))
from store_search_ai.pipeline.common import sha256_file, write_model_manifest

TRAIN_PAIRS_PATH = PROJECT_DIR / "data" / "finetune" / "train_pairs.jsonl"

"""## 모델/설정 선택

이 셀만 바꾸면 0.6B/4B/8B를 전환할 수 있다. 4B/8B는 `USE_4BIT=True` 권장(무료 T4 메모리 제약).
"""

MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"   # 4B는 "Qwen/Qwen3-Embedding-4B", 8B는 "...-8B"
TAG = "qwen3_embedding_0_6b_ft_v1"
USE_4BIT = False                          # 4B/8B로 바꾸면 True 권장
LORA_RANK = 16
LORA_ALPHA = 32
NUM_EPOCHS = 3
BATCH_SIZE = 32                           # 4B/8B + 4bit면 4~8로 낮출 것
OUTPUT_DIR = FINETUNE_RUN_DIR / TAG

"""## 학습 데이터를 ms-swift 스키마로 변환

우리 jsonl: {"query_id","query","positive","negatives":[...]}
ms-swift embedding SFT jsonl(best-effort, --help로 확인할 것): {"query","response","rejected_response":[...]}
"""

SWIFT_DATASET_PATH = FINETUNE_RUN_DIR / f"{TAG}_swift_dataset.jsonl"

n = 0
with TRAIN_PAIRS_PATH.open(encoding="utf-8") as fin, SWIFT_DATASET_PATH.open(
    "w", encoding="utf-8"
) as fout:
    for line in fin:
        row = json.loads(line)
        fout.write(
            json.dumps(
                {
                    "query": row["query"],
                    "response": row["positive"],
                    "rejected_response": row["negatives"],
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        n += 1

print(f"[INFO] ms-swift 데이터셋 {n}건 저장: {SWIFT_DATASET_PATH}")

"""## swift sft 실행

**실행 전에 `!swift sft --help`로 아래 플래그명이 현재 설치된 버전과 맞는지 확인하세요.**
특히 `--task_type`, `--loss_type`, 4bit 양자화 플래그(`--quant_bits`/`--bnb_4bit_...`)는
버전별로 이름이 다를 수 있습니다.
"""

quant_args = ["--quant_method", "bnb", "--quant_bits", "4"] if USE_4BIT else []

command = [
    "swift", "sft",
    "--model", MODEL_ID,
    "--task_type", "embedding",
    "--loss_type", "infonce",
    "--train_type", "lora",
    "--lora_rank", str(LORA_RANK),
    "--lora_alpha", str(LORA_ALPHA),
    "--dataset", str(SWIFT_DATASET_PATH),
    "--num_train_epochs", str(NUM_EPOCHS),
    "--per_device_train_batch_size", str(BATCH_SIZE),
    "--output_dir", str(OUTPUT_DIR),
    "--save_only_model", "true",
    *quant_args,
]

print("[INFO] 실행할 명령:")
print(" ".join(command))

import subprocess

subprocess.run(command, check=True)

manifest_path = write_model_manifest(
    OUTPUT_DIR,
    {
        "tag": TAG,
        "base_model_id": MODEL_ID,
        "framework": "ms-swift+lora",
        "hyperparameters": {
            "train_type": "lora",
            "lora_rank": LORA_RANK,
            "lora_alpha": LORA_ALPHA,
            "num_train_epochs": NUM_EPOCHS,
            "per_device_train_batch_size": BATCH_SIZE,
            "quantization": "bnb_4bit" if USE_4BIT else None,
            "loss_type": "infonce",
        },
        "training_data": {
            "source": str(TRAIN_PAIRS_PATH),
            "sha256": sha256_file(TRAIN_PAIRS_PATH),
            "num_examples": n,
        },
        "notes": (
            "LoRA adapter만 저장됨 — 평가/서빙 전 베이스 모델과 merge가 필요할 수 있음 "
            "(swift export --adapters <output_dir> --merge_lora true 등, --help로 확인)."
        ),
    },
)

print(f"\n[완료] 학습 결과: {OUTPUT_DIR}")
print(f"[완료] model_manifest.json: {manifest_path}")
print("LoRA adapter만 저장됩니다 — 평가/서빙에 쓰려면 베이스 모델과 merge가 필요할 수 있습니다")
print("(ms-swift의 `swift export --adapters <output_dir> --merge_lora true` 등을 --help로 확인).")
print("merge된(또는 adapter) 모델 폴더를 로컬 models/<태그>/로 내려받은 뒤(model_manifest.json 포함),")
print("configs/models/<태그>.yaml에서 model_id를 그 로컬 경로로 지정하세요.")
