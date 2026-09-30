# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_simple.ipynb

Colab(무료 T4 포함)에서 Snowflake Arctic(`arctic_ko.yaml`), BGE-M3(`bge_m3.yaml`) 등 Qwen3가 아닌
임베딩 모델을 full fine-tuning한다. Qwen3-Embedding은 `colab/run_finetune_qwen3.py`(LoRA) 참고 —
두 스크립트는 설정값만 다르고 학습 코드는 `store_search_ai.training.st_finetune.run_finetune()`
하나를 같이 쓴다(팀원마다 학습 코드가 달라서 결과를 비교할 수 없게 되는 일을 막기 위함).

무엇이 자동으로 처리되나 (docs/TRAINING.md 2절):
- T4는 bf16 미지원 → fp16 AMP 자동 선택(L4/A100이면 bf16). loss가 NaN이 되면 저장 없이 중단.
- (query, positive)마다 한 행 + hard negative 고정 개수 + 같은 텍스트가 한 배치에 두 번 안 들어가게
  NO_DUPLICATES 배치 + GISTEmbedLoss(같은 family query끼리 서로의 정답을 오답으로 배우는 문제 완화).
- 학습 절반 지점에서 **체크포인트를 딱 한 번** Drive `runs/finetune/<TAG>.ckpt/`에 저장 — Colab 연결이
  끊기면 RESUME_TAG에 그 TAG를 넣고 같은 설정으로 다시 실행하면 거기서부터 이어서 학습한다.
  최종 모델 저장이 성공하면 이 체크포인트는 자동으로 지운다.
- **Drive에 남는 건 최종 모델 하나**(fp16). 저장 후 다시 로드해서 임베딩이 같은지 검증하고, 내 run 중
  최신 3개만 남기고 오래된 건 지운다(KEEP 파일 있는 run 제외, 다른 팀원의 run은 절대 안 건드림).

사용 전 준비 (한 번만):
  1. 학습 데이터(data/finetune/train_pairs.jsonl + train_pairs.meta.json) 준비 — 데이터 담당이 git으로
     배포한 것을 `git pull`로 받는다(직접 만들 때만 `python scripts/prepare_finetune_dataset.py`)
  2. 로컬에서 `python scripts/pack_for_colab.py` → `colab_upload/project/` 폴더가 생긴다
     (코드 + configs/models + 학습 데이터 + git 커밋 정보 code_version.json).
     Drive `내 드라이브/store-search-ai/`의 기존 `project` 폴더를 지우고 이 `project` 폴더를 올린다.
  3. 아래 "설정" 셀의 OWNER(필수)와 NOTE(바꾼 게 있으면)를 적고 전체 실행
  4. 끝나면 Drive `runs/finetune/<TAG>/`를 로컬 `models/<TAG>/`로 내려받고,
     그 안의 `eval_config.yaml`을 `configs/models/<TAG>.yaml`로 복사해서
     `python scripts/14_run_model_eval.py --model-config configs/models/<TAG>.yaml --split val`
     (평가 결과는 자동으로 models/<TAG>/model_manifest.json에 쌓인다)
  5. 서비스 후보로 남길 run은 맨 아래 셀의 한 줄로 그 폴더에 빈 파일 `KEEP`을 만들어 자동 정리에서 보호
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
else:
    print("[경고] GPU가 없습니다 — 런타임 > 런타임 유형 변경 > T4 GPU")

# 팀 전체가 같은 버전으로 학습해야 결과를 비교할 수 있다 — 버전을 바꾸려면 팀과 합의 후
# 이 줄과 colab/run_finetune_qwen3.py, pyproject.toml의 train extra를 같이 바꿀 것.
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

**OWNER만 필수로 바꾸면 된다.** 나머지는 팀 공통 기본값 — 결과를 서로 비교하려면 합의 없이 바꾸지
말 것(바꾼 값은 전부 model_manifest.json에 자동으로 남는다).
"""

OWNER = ""                              # 필수: 본인 이름(영문 소문자, 예: "jisu") — run 이름/정리 범위에 쓰임
MODEL_CONFIG = "arctic_ko.yaml"         # 또는 "bge_m3.yaml"
RESUME_TAG = None                       # 연결이 끊긴 run을 이어서 학습할 때만: 그 run의 TAG
                                        # (Drive runs/finetune/<TAG>.ckpt/ 의 <TAG>, 나머지 설정은 처음과 같게)
SAVE_MID_CHECKPOINT = True              # 절반 지점에 한 번 Drive 저장(약 7GB, 끝나면 자동 삭제). 공간이 없으면 False
NOTE = ""                               # 이 run에서 바꾼 것 한 줄(예: "negative 5개", "쿼리 공백 제거 전처리 추가")

cfg = FinetuneConfig(
    model_config_path=PROJECT_DIR / "configs" / "models" / MODEL_CONFIG,
    train_pairs_path=PROJECT_DIR / "data" / "finetune" / "train_pairs.jsonl",
    run_root=DRIVE_ROOT / "runs" / "finetune",
    owner=OWNER,
    num_epochs=2,
    batch_size=32,              # T4에서 OOM이 나면 16으로(manifest에 기록됨)
    learning_rate=2e-5,
    num_hard_negatives=3,
    max_positives_per_query=32,
    loss="gist",                # OOM이 나면 "mnrl"(guide 모델을 안 올림)
    save_mid_checkpoint=SAVE_MID_CHECKPOINT,
    resume_tag=RESUME_TAG,
    keep_last_runs=3,           # 내 run 중 최신 3개만 Drive에 남김(KEEP 파일 있는 run은 별도 보존)
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
