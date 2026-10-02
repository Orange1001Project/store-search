# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_qwen3.ipynb

Colab(무료 T4 포함)에서 Qwen3-Embedding을 LoRA로 fine-tuning한 뒤 베이스 모델에 merge해서
sentence-transformers 포맷의 전체 모델 하나로 저장한다. 학습 코드는
`colab/run_finetune_simple.ipynb`와 같은 `store_search_ai.training.st_finetune.run_finetune()`이다 —
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

사용 전 준비는 `colab/run_finetune_simple.ipynb` 맨 위 설명과 동일(로컬에서 `python scripts/pack_for_colab.py` →
`colab_upload/project/`를 Drive `store-search-ai/project`로 올리기). 학습이 끝나면 **같은 노트북에서 바로 val 채점**
(기준 zero-shot 모델 대비) → 리더보드까지 본다 — 로컬로 옮길 필요 없음.
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
