# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_simple.ipynb

Colab(무료 T4 포함)에서 Snowflake Arctic(`arctic_ko.yaml`), BGE-M3(`bge_m3.yaml`) 등 Qwen3가 아닌
임베딩 모델을 full fine-tuning한다. Qwen3-Embedding은 `colab/run_finetune_qwen3.ipynb`(LoRA) 참고 —
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
     (코드 + configs + 학습 데이터 + 평가용 corpus·queries·val/test 정답 + git 커밋 정보 code_version.json).
     Drive `내 드라이브/store-search-ai/`의 기존 `project` 폴더를 지우고 이 `project` 폴더를 올린다.
  3. 아래 "설정" 셀의 OWNER(필수)와 NOTE(바꾼 게 있으면)를 적고 위에서부터 실행
     → 학습 → **바로 val 채점**(기준 zero-shot 모델 대비) → 리더보드까지 이 노트북 안에서 끝난다.
  4. 코드를 고치고 싶으면 Drive의 src/ 파일을 Colab 편집기에서 고친 뒤 학습 셀부터 다시 실행(docs/TRAINING_TEAM.md 3-2절)
  5. 남길 run은 맨 아래 셀로 KEEP 표시. 실험이 다 끝나면 Drive 결과를 로컬로 내려받아
     `python scripts/import_colab_results.py --drive-dir <내려받은 store-search-ai 폴더> --verify`로 저장소에 정리
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")
else:
    print("[경고] GPU가 없습니다 — 런타임 > 런타임 유형 변경 > T4 GPU")

# %%
# Colab에 미리 깔린 torch/transformers/sentence-transformers/peft/datasets/accelerate를 **그대로** 쓴다.
# (예전처럼 옛 버전을 강제로 설치하면 huggingface_hub·fsspec까지 내려가 Colab 기본 패키지와 충돌한다 —
#  버전마다 달라진 API는 store_search_ai.common.hf_compat이 맞춘다.) 채점용 두 개만 설치 — 둘 다 HF 패키지를 건드리지 않음.
get_ipython().system('pip -q install "ir-measures==0.4.3" "pytrec-eval-terrier==0.5.10"')

# %%
from google.colab import drive

drive.mount("/content/drive")

# %%
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

from store_search_ai.common.hf_compat import check_environment

check_environment()  # 버전 출력 + 최소 버전 미달·채점 패키지 누락이면 여기서 바로 알려 줌(실제 버전은 기록에도 남음)

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

# %%
final_dir = run_finetune(cfg)

"""## 평가 (val) — 학습한 모델을 바로 채점

로컬 `scripts/13_evaluate_run.py`와 **같은 공식 evaluator 함수**로 채점한다(Colab 점수 = 로컬 점수).
처음 한 번은 비교 기준인 **zero-shot 베이스 모델**도 자동으로 평가한다(문서 21만 개 인코딩이라 모델당 수 분~수십 분).
결과는 Drive `runs/model_eval/`(run.csv), `runs/evaluation/`(지표 json)에 쌓이고, 모델 폴더의 manifest에도 기록된다.

학습 없이 이미 있는 run을 다시 평가하려면 학습 셀은 건너뛰고 `EVAL_RUN_TAG`에 그 run의 TAG를 넣는다.
"""

# %%
import gc

from store_search_ai.evaluation.model_evaluation import (
    collect_leaderboard,
    evaluate_model,
    format_report,
    load_eval_inputs,
)
from store_search_ai.pipeline.common import load_config

EVAL_RUN_TAG = None                     # 학습 없이 평가만: Drive runs/finetune/ 의 TAG (None이면 방금 학습한 모델)
RUN_ROOT = DRIVE_ROOT / "runs" / "model_eval"
EVAL_ROOT = DRIVE_ROOT / "runs" / "evaluation"

eval_inputs = load_eval_inputs(PROJECT_DIR)  # corpus·queries·벤치마크 설정(이 세션에서 한 번 읽으면 재사용)
base_config = load_config(PROJECT_DIR / "configs" / "models" / MODEL_CONFIG)

# %%
if not (RUN_ROOT / base_config["name"] / "run_t1_minimal_val.csv").exists():
    print(f"[기준 모델] {base_config['name']} zero-shot 평가 (처음 한 번만)")
    baseline = evaluate_model(base_config, eval_inputs, run_root=RUN_ROOT, eval_root=EVAL_ROOT)
    print(format_report(baseline["report"]))
    del baseline
    gc.collect()
    torch.cuda.empty_cache()

if EVAL_RUN_TAG:
    run_dir = DRIVE_ROOT / "runs" / "finetune" / EVAL_RUN_TAG
elif "final_dir" in globals():
    run_dir = final_dir
else:
    raise SystemExit("학습 셀을 실행하거나 EVAL_RUN_TAG에 평가할 run의 TAG를 넣으세요.")

eval_config = {**load_config(run_dir / "eval_config.yaml"), "model_id": str(run_dir)}
result = evaluate_model(eval_config, eval_inputs, run_root=RUN_ROOT, eval_root=EVAL_ROOT,
                        baseline_tag=base_config["name"])
print(format_report(result["report"]))
del result
gc.collect()
torch.cuda.empty_cache()

"""## 리더보드 (val) — Drive에 쌓인 평가 전부

nDCG@10 순. `ΔnDCG@10`/`p(nDCG@10)`은 각 run의 기준(zero-shot 베이스 모델) 대비 차이와 paired 검정 p-value.
**차이가 0.03보다 작거나 p가 크면 "개선"이라고 하지 않는다.** Judged@10이 낮으면 점수가 실제보다 낮게 나왔을 수 있다.
"""

# %%
leaderboard = collect_leaderboard(EVAL_ROOT, "val")
cols = ["tag", "nDCG@10", "ΔnDCG@10", "p(nDCG@10)", "Judged@10", "Recall@100", "MRR@100", "libs"]
print(leaderboard[[c for c in cols if c in leaderboard.columns]].to_string(index=False))

"""## (평가 후) 좋은 run을 KEEP으로 남기기

Drive는 내 run 중 최신 3개만 남기고 자동으로 지운다. 서비스 후보·공유할 run은 아래 한 줄로 표시하면
절대 지워지지 않는다(Drive 화면에서는 빈 파일을 만들 수 없어서 이렇게 한다). TAG만 바꿔서 실행.
"""

# (DRIVE_ROOT / "runs" / "finetune" / "여기에_TAG" / "KEEP").touch()

"""## (팀이 최종 후보를 정한 뒤 한 번만) test 평가

모델·설정 선택은 전부 val로 한다. test는 최종 후보가 확정된 뒤 **한 번만** 본다 — 그래서 기본값은 꺼져 있다.
"""

# %%
FINAL_TEST = False                      # 최종 후보 확정 후에만 True

if FINAL_TEST:
    if not (RUN_ROOT / base_config["name"] / "run_t1_minimal_test.csv").exists():
        evaluate_model(base_config, eval_inputs, run_root=RUN_ROOT, eval_root=EVAL_ROOT, split="test", allow_test=True)
    test_result = evaluate_model(eval_config, eval_inputs, run_root=RUN_ROOT, eval_root=EVAL_ROOT, split="test",
                                 allow_test=True, baseline_tag=base_config["name"])
    print(format_report(test_result["report"]))
