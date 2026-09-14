# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_simple.ipynb

Colab에서 sentence-transformers 표준 `.fit()`으로 임베딩 모델을 fine-tuning한다.
Snowflake Arctic(`arctic_ko.yaml`), BGE-M3(`bge_m3.yaml`) 등 **Qwen3가 아닌 모델을 간단히**
돌려볼 때 쓴다(ms-swift 없이, sentence-transformers만으로 어떤 HF 인코더 모델에도 적용 가능).
Qwen3-Embedding 본 학습은 `colab/run_finetune_qwen3.py`(ms-swift, LoRA) 참고.

MultipleNegativesRankingLoss를 쓴다: in-batch negative + `train_pairs.jsonl`의 명시적 hard
negative를 InputExample(texts=[query, positive, *negatives])로 그대로 넣을 수 있다(같은 배치
안의 다른 샘플들도 자동으로 추가 negative가 된다) — GPL/E5/BGE류가 흔히 쓰는 대조학습 방식과 동일.

사용 전 준비 (한 번만):
  1. 로컬에서 `python scripts/prepare_finetune_dataset.py`로 data/finetune/train_pairs.jsonl 생성
  2. Drive에 아래 업로드:
       project/src/store_search_ai/   (model_manifest.json 기록용, 그대로 폴더째)
       project/data/finetune/train_pairs.jsonl
       project/configs/models/<베이스모델>.yaml   (예: arctic_ko.yaml, bge_m3.yaml)
  3. 이 스크립트를 Colab에서 실행 (MODEL_CONFIG_PATH만 바꾸면 됨) — 끝나면 OUTPUT_DIR에
     `model_manifest.json`도 같이 저장된다(base 모델, 하이퍼파라미터, 학습 데이터 sha256 등).
  4. 끝나면 Drive의 runs/finetune/<태그>/ 를 로컬 models/ 밑으로 내려받고(manifest 포함),
     configs/models/<태그>.yaml을 새로 만들어 model_id를 그 로컬 경로로 지정한 뒤
     scripts/14_run_model_eval.py --model-config configs/models/<태그>.yaml --split val 로 평가
     (평가 결과가 자동으로 model_manifest.json의 evaluations 목록에 추가된다)
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))

get_ipython().system('pip -q install -U "sentence-transformers>=2.7.0" accelerate')

from google.colab import drive

drive.mount("/content/drive")

import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
PROJECT_DIR = DRIVE_ROOT / "project"
FINETUNE_RUN_DIR = DRIVE_ROOT / "runs" / "finetune"
FINETUNE_RUN_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT_DIR / "src"))

from store_search_ai.pipeline.common import load_config, sha256_file, write_model_manifest

TRAIN_PAIRS_PATH = PROJECT_DIR / "data" / "finetune" / "train_pairs.jsonl"

"""## 모델/설정 선택

이 셀만 바꾸면 다른 베이스 모델로 전환할 수 있다.
"""

MODEL_CONFIG_PATH = PROJECT_DIR / "configs" / "models" / "arctic_ko.yaml"   # 또는 bge_m3.yaml 등
NUM_EPOCHS = 3
BATCH_SIZE = 16
WARMUP_RATIO = 0.1

model_config = load_config(MODEL_CONFIG_PATH)
TAG = f"{model_config['name']}_ft_v1"
OUTPUT_DIR = FINETUNE_RUN_DIR / TAG

print(f"[INFO] base model: {model_config['model_id']}  ->  tag: {TAG}")

"""## 학습쌍 로드 -> InputExample

같은 query 안에서 positive/negative를 한 번에 넣는다 — MultipleNegativesRankingLoss가
positive는 대각선(정답)으로, 나머지(다른 샘플의 positive/negative 전부 포함)는 자동으로
negative로 취급한다.
"""

import json

from sentence_transformers import InputExample, SentenceTransformer, losses
from torch.utils.data import DataLoader

train_examples = []
with TRAIN_PAIRS_PATH.open(encoding="utf-8") as f:
    for line in f:
        row = json.loads(line)
        texts = [row["query"], row["positive"], *row["negatives"]]
        train_examples.append(InputExample(texts=texts))

print(f"[INFO] 학습 쌍 {len(train_examples)}개 로드")

"""## Fine-tuning"""

model = SentenceTransformer(model_config["model_id"])
train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=BATCH_SIZE)
train_loss = losses.MultipleNegativesRankingLoss(model)

warmup_steps = int(len(train_dataloader) * NUM_EPOCHS * WARMUP_RATIO)

model.fit(
    train_objectives=[(train_dataloader, train_loss)],
    epochs=NUM_EPOCHS,
    warmup_steps=warmup_steps,
    show_progress_bar=True,
    output_path=str(OUTPUT_DIR),
)

manifest_path = write_model_manifest(
    OUTPUT_DIR,
    {
        "tag": TAG,
        "base_model_id": model_config["model_id"],
        "framework": "sentence-transformers",
        "hyperparameters": {
            "loss": "MultipleNegativesRankingLoss",
            "num_epochs": NUM_EPOCHS,
            "batch_size": BATCH_SIZE,
            "warmup_ratio": WARMUP_RATIO,
        },
        "training_data": {
            "source": str(TRAIN_PAIRS_PATH),
            "sha256": sha256_file(TRAIN_PAIRS_PATH),
            "num_examples": len(train_examples),
        },
    },
)

print(f"\n[완료] fine-tuned 모델 저장: {OUTPUT_DIR}")
print(f"[완료] model_manifest.json: {manifest_path}")
print("이 폴더를 로컬 models/<태그>/로 내려받은 뒤(model_manifest.json 포함),")
print("configs/models/<태그>.yaml에서 model_id를 그 로컬 경로로 지정하고")
print("scripts/14_run_model_eval.py로 평가하세요 (평가 결과가 자동으로 manifest에 추가됩니다).")
