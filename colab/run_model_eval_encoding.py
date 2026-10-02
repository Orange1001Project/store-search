# -*- coding: utf-8 -*-
"""store_search_ai_colab_model_eval_encode.ipynb

Colab에서 여러 모델을 한 번에 평가한다: 모델 로드 → corpus/query 인코딩 → exact cosine 검색 → **공식 채점**
→ 리더보드. zero-shot 모델(HF Hub ID)이든 fine-tuned 모델(`eval_config.yaml`, `model_id: models/<TAG>`)이든
같은 코드로 처리한다.

채점은 로컬 `scripts/13_evaluate_run.py`와 **같은 함수**(`store_search_ai.evaluation.evaluator.build_evaluation_report`)로
한다 — 그래서 여기서 본 점수가 공식 점수다(마지막에 `scripts/import_colab_results.py --verify`가 로컬에서 다시 채점해
같은지 확인한다). 학습한 모델 하나를 학습 직후 평가할 때는 이 노트북 대신 학습 노트북의 "평가" 셀을 쓰면 된다 —
이 노트북은 **zero-shot 비교표**나 **여러 run을 한꺼번에** 다시 평가할 때 쓴다.

사용 전 준비 (한 번만):
  1. 로컬에서 `python scripts/pack_for_colab.py` → `colab_upload/project/`를 Drive `내 드라이브/store-search-ai/project`로
     올린다(기존 project 폴더는 지우고). corpus·queries·val/test 정답이 같이 들어간다.
  2. 이 노트북을 Colab에서 위에서부터 실행한다.
  3. 결과: Drive `runs/model_eval/<tag>/run_<template>_<split>.csv`, `runs/evaluation/<tag>_<template>_<split>_evaluation.json`
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")

# %%
# Colab에 미리 깔린 torch/transformers/sentence-transformers/peft/datasets/accelerate를 **그대로** 쓴다.
# (예전처럼 옛 버전을 강제로 설치하면 huggingface_hub·fsspec까지 내려가 Colab 기본 패키지와 충돌한다 —
#  버전마다 달라진 API는 store_search_ai.common.hf_compat이 맞춘다.) 채점용 두 개만 설치 — 둘 다 HF 패키지를 건드리지 않음.
get_ipython().system('pip -q install "ir-measures==0.4.3" "pytrec-eval-terrier==0.5.10"')

# %%
from google.colab import drive

drive.mount("/content/drive")

# %%
import gc
import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
PROJECT_DIR = DRIVE_ROOT / "project"
RUN_ROOT = DRIVE_ROOT / "runs" / "model_eval"       # run.csv
EVAL_ROOT = DRIVE_ROOT / "runs" / "evaluation"      # 지표 json / per-query csv
FINETUNE_RUN_DIR = DRIVE_ROOT / "runs" / "finetune"
sys.path.insert(0, str(PROJECT_DIR / "src"))

# Drive의 src/ 코드를 Colab 편집기에서 고쳤으면 아래 "설정" 셀부터 다시 실행 — reload_project()가 고친 코드를 다시
# 불러온다(세션 재시작 불필요). IPython autoreload는 Colab(Python 3.13 + IPython 7.34)에서 `imp` 모듈 오류가 나서 안 쓴다.

from store_search_ai.evaluation.model_evaluation import (
    collect_leaderboard,
    evaluate_model,
    format_report,
    load_eval_inputs,
)
from store_search_ai.pipeline.common import load_config

from store_search_ai.common.hf_compat import check_environment

check_environment()  # 버전 출력 + 최소 버전 미달·채점 패키지 누락이면 여기서 바로 알려 줌(실제 버전은 기록에도 남음)

eval_inputs = load_eval_inputs(PROJECT_DIR)
print("corpus:", eval_inputs["corpus"].shape, " queries:", eval_inputs["queries"]["split"].value_counts().to_dict())

"""## 설정

- `MODEL_CONFIG_NAMES`: 평가할 `configs/models/*.yaml` 파일 이름 목록. `None`이면 전부(zero-shot 비교표용).
  학습한 모델은 그 run 폴더의 `eval_config.yaml`을 `configs/models/<TAG>.yaml`로 넣고 pack하면 여기서 고를 수 있다.
- `BASELINE_TAG`: 비교 기준 모델의 `name`(예: `"bge_m3"`). 주면 각 모델의 기준 대비 Δ·p-value를 같이 계산한다.
- test는 최종 후보를 정한 뒤 한 번만 — `SPLIT="test"`는 `ALLOW_TEST=True`일 때만 돈다.
"""

# %%
# 평가 코드(src/store_search_ai/evaluation/)를 고쳤으면 이 셀부터 다시 실행 — 고친 코드를 다시 불러온다
from store_search_ai.common.dev_reload import reload_project

reload_project()
from store_search_ai.evaluation.model_evaluation import (
    collect_leaderboard,
    evaluate_model,
    format_report,
)
from store_search_ai.pipeline.common import load_config

MODEL_CONFIG_NAMES = None      # 예: ["bge_m3.yaml", "qwen3_0_6b.yaml", "qwen3_0_6b_store.yaml"]
BASELINE_TAG = None            # 예: "qwen3_embedding_0_6b"
SPLIT = "val"
ALLOW_TEST = False
TEMPLATE = "t1_minimal"        # 공식 문서 표현(docs/PIPELINE.md 1절). T2/T3 실험할 때만 바꾼다
SKIP_EXISTING = True           # 이미 평가한 모델은 건너뜀(연결이 끊겨 다시 실행할 때)

MODEL_CONFIG_DIR = PROJECT_DIR / "configs" / "models"
paths = [MODEL_CONFIG_DIR / n for n in MODEL_CONFIG_NAMES] if MODEL_CONFIG_NAMES else sorted(MODEL_CONFIG_DIR.glob("*.yaml"))
missing = [p for p in paths if not p.exists()]
assert not missing, f"찾을 수 없는 모델 설정: {missing}"


def resolve_config(path):
    config = load_config(path)
    # fine-tuned 모델의 eval_config는 로컬 경로(models/<TAG>)를 가리킨다 → Colab에서는 Drive runs/finetune/<TAG>
    if str(config["model_id"]).startswith("models/"):
        config = {**config, "model_id": str(FINETUNE_RUN_DIR / Path(config["model_id"]).name)}
    return config


def corpus_key(config):
    """문서 임베딩을 좌우하는 값 — 같으면 query prompt만 다른 변형끼리 문서 임베딩을 재사용한다."""
    return (config["model_id"], config.get("torch_dtype"), config.get("target_dimension"),
            config.get("normalize_embeddings", True))


# 기준 모델을 먼저, 그다음 같은 모델(문서 임베딩이 같은 설정)끼리 붙여서 → 모델 로드·문서 인코딩을 한 번만
configs = sorted((resolve_config(p) for p in paths),
                 key=lambda c: (c["name"] != BASELINE_TAG, str(corpus_key(c)), c["name"]))
print("평가 순서:", [c["name"] for c in configs])

"""## 평가 실행 (모델별로 순회)"""

# %%
encoder, encoder_key, doc_embeddings = None, None, None
for config in configs:
    if SKIP_EXISTING and (RUN_ROOT / config["name"] / f"run_{TEMPLATE}_{SPLIT}.csv").exists():
        print(f"\n===== {config['name']}: 이미 평가됨 — 건너뜀 =====")
        continue
    print(f"\n===== {config['name']} ({config['model_id']}) =====")
    if corpus_key(config) != encoder_key:
        encoder, doc_embeddings = None, None
        gc.collect()
        torch.cuda.empty_cache()
    result = evaluate_model(
        config, eval_inputs, run_root=RUN_ROOT, eval_root=EVAL_ROOT, split=SPLIT, template=TEMPLATE,
        baseline_tag=BASELINE_TAG, allow_test=ALLOW_TEST, encoder=encoder, doc_embeddings=doc_embeddings,
    )
    encoder, doc_embeddings, encoder_key = result["encoder"], result["doc_embeddings"], corpus_key(config)
    print(format_report(result["report"]))

del encoder, doc_embeddings
gc.collect()
torch.cuda.empty_cache()

"""## 리더보드

nDCG@10 순. 기준 모델(`BASELINE_TAG`)을 줬으면 `ΔnDCG@10`/`p(nDCG@10)`이 같이 나온다.
**차이가 0.03보다 작거나 p가 크면 "개선"이라고 하지 않는다.** Judged@10이 낮으면 점수가 실제보다 낮게 나왔을 수 있다
(지금 정답은 키워드 검색 pool로만 만들어서, 모델이 새로 찾은 문서는 판정이 없어 오답으로 계산됨).
"""

# %%
leaderboard = collect_leaderboard(EVAL_ROOT, SPLIT)
cols = ["tag", "nDCG@10", "ΔnDCG@10", "p(nDCG@10)", "Judged@10", "Recall@100", "MRR@100", "Precision@10", "libs"]
print(leaderboard[[c for c in cols if c in leaderboard.columns]].to_string(index=False))
