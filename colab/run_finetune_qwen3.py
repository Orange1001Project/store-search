# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_qwen3.ipynb

Colab(무료 T4 포함)에서 Qwen3-Embedding을 LoRA로 fine-tuning한 뒤 베이스 모델에 merge해서
sentence-transformers 포맷의 전체 모델 하나로 저장한다. 학습 코드는
`colab/run_finetune_simple.py`와 같은 `store_search_ai.training.st_finetune.run_finetune()`이다 —
차이는 LoRA를 켜고 learning rate가 다른 것뿐.

**왜 ms-swift를 안 쓰나** (예전 버전은 ms-swift였다):
- ms-swift 예제는 bf16/flash-attention 기준인데 T4는 둘 다 지원하지 않는다.
- ms-swift는 LoRA adapter를 `output/vX-날짜/checkpoint-N/`에 저장한다. merge를 해도
  sentence-transformers 설정(last-token pooling, query prompt)이 빠져서, `SentenceTransformer(path)`로
  불러오면 **에러 없이 mean pooling으로 로드돼 임베딩이 틀어진다** — 우리 평가 harness(14번)와 서빙이
  전부 sentence-transformers 기준이라 치명적이다.
- 버전마다 데이터 포맷/플래그가 바뀌었다(`query/response` → `messages/positive_messages`,
  `--train_type` → `--tuner_type`).
sentence-transformers + peft로 학습하면 저장 결과가 처음부터 베이스 모델과 같은 포맷(pooling,
prompt, normalize 포함)이라 이 문제가 전부 사라진다. 저장 직후 다시 로드해서 임베딩이 같은지도
자동으로 검증한다.

**query instruction**: 학습 때 query에 붙는 prompt는 `configs/models/qwen3_*.yaml`의
`query_prompt_name`(="query") prompt 그대로다 — 평가(14번)와 서빙에서도 `prompt_name="query"`만 쓰면
학습 때와 똑같은 문자열이 붙는다. 한국어 매장 검색용 instruction으로 바꾸고 싶으면
QUERY_PROMPT_OVERRIDE에 문자열을 넣으면 그 문자열로 학습하고, 저장되는 모델의 "query" prompt도
그 문자열로 바뀐다(zero-shot 모델과 비교할 때 이 차이를 꼭 같이 적을 것).

T4(15GB) 기준 모델별 설정:
  0.6B: 아래 기본값 그대로 (LoRA, fp32 베이스, gist)
  4B  : BASE_DTYPE="float16", BATCH_SIZE=8, LOSS="mnrl" (guide 모델까지 올리면 OOM).
        fp16 베이스는 overflow로 loss가 NaN이 될 수 있다 — 그러면 저장 없이 중단되니 L4/A100을 쓸 것.
  8B  : T4에서는 불가(L4/A100 필요).

사용 전 준비는 `colab/run_finetune_simple.py` 상단과 동일(로컬에서 `python scripts/pack_for_colab.py` →
`colab_upload/project/`를 Drive `store-search-ai/project`로 올리기).
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
else:
    print("[경고] GPU가 없습니다 — 런타임 > 런타임 유형 변경 > T4 GPU")

# colab/run_finetune_simple.py와 반드시 같은 버전 (팀 합의 없이 바꾸지 말 것)
get_ipython().system(
    'pip -q install "sentence-transformers==3.4.1" "transformers==4.51.3" "peft==0.15.2" '
    '"datasets==3.5.0" "accelerate==1.6.0"'
)

from google.colab import drive

drive.mount("/content/drive")

import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
PROJECT_DIR = DRIVE_ROOT / "project"
sys.path.insert(0, str(PROJECT_DIR / "src"))

# Colab 편집기에서 Drive의 src/ 코드를 고치면(왼쪽 파일 탐색기 → drive/MyDrive/store-search-ai/project/src/...
# 더블클릭) 세션을 다시 시작하지 않아도 다음 셀 실행 때 고친 코드가 자동으로 다시 import된다.
# 고친 코드는 학습 때 모델 폴더의 code_snapshot.zip에 그대로 저장된다(docs/TRAINING_TEAM.md 3절).
get_ipython().run_line_magic("load_ext", "autoreload")
get_ipython().run_line_magic("autoreload", "2")

from store_search_ai.training.st_finetune import FinetuneConfig, run_finetune

"""## 설정

OWNER만 필수. 4B로 바꿀 때는 위 docstring의 "T4 기준 모델별 설정"대로 세 값을 같이 바꿀 것.
"""

OWNER = ""                              # 필수: 본인 이름(영문 소문자)
MODEL_CONFIG = "qwen3_0_6b.yaml"        # 4B는 "qwen3_4b.yaml"
BASE_DTYPE = "float32"                  # 4B + T4면 "float16"
BATCH_SIZE = 32                         # 4B + T4면 8
LOSS = "gist"                           # 4B + T4면 "mnrl"
QUERY_PROMPT_OVERRIDE = None            # 예: "Instruct: 한국 지역 가맹점 검색 질의에 맞는 매장을 찾으세요\nQuery:"
RESUME_TAG = None                       # 연결이 끊긴 run을 이어서 학습할 때만: 그 run의 TAG
                                        # (Drive runs/finetune/<TAG>.ckpt/ 의 <TAG>, 나머지 설정은 처음과 같게)
SAVE_MID_CHECKPOINT = True              # 절반 지점에 한 번 Drive 저장(LoRA라 수십 MB, 끝나면 자동 삭제)
NOTE = ""                               # 이 run에서 바꾼 것 한 줄

cfg = FinetuneConfig(
    model_config_path=PROJECT_DIR / "configs" / "models" / MODEL_CONFIG,
    train_pairs_path=PROJECT_DIR / "data" / "finetune" / "train_pairs.jsonl",
    run_root=DRIVE_ROOT / "runs" / "finetune",
    owner=OWNER,
    num_epochs=2,
    batch_size=BATCH_SIZE,
    learning_rate=1e-4,         # LoRA는 full fine-tuning보다 lr을 크게 쓴다
    num_hard_negatives=3,
    max_positives_per_query=32,
    loss=LOSS,
    query_prompt_override=QUERY_PROMPT_OVERRIDE,
    lora_rank=16,
    lora_alpha=32,
    base_dtype=BASE_DTYPE,
    save_mid_checkpoint=SAVE_MID_CHECKPOINT,
    resume_tag=RESUME_TAG,
    keep_last_runs=3,
    note=NOTE,
)

final_dir = run_finetune(cfg)

print("\n다음 단계:")
print(f"  1. Drive {final_dir} 폴더를 로컬 models/{final_dir.name}/ 로 내려받기")
print(f"  2. models/{final_dir.name}/eval_config.yaml 을 configs/models/{final_dir.name}.yaml 로 복사")
print(f"  3. python scripts/14_run_model_eval.py --model-config configs/models/{final_dir.name}.yaml --split val")

"""## (평가 후) 좋은 run을 KEEP으로 남기기

Drive는 내 run 중 최신 3개만 남기고 자동으로 지운다. 서비스 후보·공유할 run은 아래 한 줄로 표시하면
절대 지워지지 않는다(Drive 화면에서는 빈 파일을 만들 수 없어서 이렇게 한다). TAG만 바꿔서 실행.
"""

# (DRIVE_ROOT / "runs" / "finetune" / "여기에_TAG" / "KEEP").touch()
