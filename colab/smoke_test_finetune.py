# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_smoke_test.ipynb

실제 학습 데이터 없이 **가짜 데이터로 학습 코드 전체를 Colab GPU에서 한 번 검증**한다.
push 전, 또는 라이브러리 버전/Colab 환경이 바뀌었을 때 돌려서 "학습 → 중간 체크포인트 → 이어서 학습 →
merge/저장 → 재로드 검증 → manifest → 체크포인트 삭제"가 끝까지 되는지 확인하는 용도다.
나오는 모델 자체는 쓸모없다(가짜 데이터).

- 결과는 `runs/finetune_smoke/`(실제 run과 다른 폴더)에만 저장되고, OWNER는 "smoke"로 고정 —
  실제 run의 자동 정리와 절대 섞이지 않는다.
- 테스트는 두 단계:
    1단계: RESUME_TAG = None 으로 실행 → `[체크포인트] ... 저장 완료` 가 찍히면 **런타임 > 실행 중단**
    2단계: 그 로그에 나온 TAG를 RESUME_TAG에 넣고 이 셀부터 다시 실행 → 끝까지 가는지 확인
  (중단 없이 끝까지 가게 두면 재개 테스트만 빠지고 나머지는 전부 검증된다.)

Drive 준비: 로컬에서 `python scripts/pack_for_colab.py` → `colab_upload/project/`를 Drive `store-search-ai/project`로
올리기(학습 데이터는 없어도 됨 — 이 스크립트가 가짜 데이터를 만든다)
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")

# %%
# colab/run_finetune_*.py와 같은 버전 (여기서 설치가 되는지 확인하는 것도 테스트의 일부)
get_ipython().system(
    'pip -q install "sentence-transformers==3.4.1" "transformers==4.51.3" "peft==0.15.2" '
    '"datasets==3.5.0" "accelerate==1.6.0"'
)

# %%
from google.colab import drive

drive.mount("/content/drive")

# %%
import json
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

SMOKE_ROOT = DRIVE_ROOT / "runs" / "finetune_smoke"
SMOKE_ROOT.mkdir(parents=True, exist_ok=True)

"""## 가짜 학습 데이터

query 200개 × positive 16개 = 3,200행, batch 32 → epoch당 약 100 step(2 epoch 약 200 step). T4에서 몇 분
걸리므로 절반 지점 체크포인트 로그를 보고 중단할 시간이 충분하다. 텍스트는 전부 서로 다르게 만든다
(같은 텍스트가 많으면 NO_DUPLICATES 배치가 작게 쪼개져 실제 학습과 다르게 돈다).
"""

N_QUERIES, N_POSITIVES, N_NEGATIVES = 200, 16, 4
pairs_path = SMOKE_ROOT / "smoke_train_pairs.jsonl"
with pairs_path.open("w", encoding="utf-8", newline="\n") as f:
    for i in range(N_QUERIES):
        record = {
            "query_id": f"smoke_{i}",
            "query": f"테스트 질의 {i}번 매장",
            "positives": [f"가맹점명: 정답매장{i}-{j} / 취급품목: 품목{i}" for j in range(N_POSITIVES)],
            "negatives": [f"가맹점명: 오답매장{i}-{k} / 취급품목: 기타{i}-{k}" for k in range(N_NEGATIVES)],
        }
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
print(f"[INFO] 가짜 데이터: {pairs_path}  (meta.json이 없다는 [경고]는 이 테스트에서는 정상)")

"""## 설정 — 테스트할 모델 하나를 고른다

- `"arctic"`: full fine-tuning + GIST + 약 7GB 체크포인트(Drive 여유 공간 필요)
- `"qwen"`  : Qwen3-Embedding-0.6B LoRA → merge (LoRA 전용 재개 로직을 검증)
push 전에는 **두 개 다** 한 번씩 돌려보는 것을 권장.
"""

TARGET = "qwen"          # "qwen" 또는 "arctic"
RESUME_TAG = None        # 2단계에서만: 1단계 [체크포인트] 로그에 나온 TAG

common = dict(
    train_pairs_path=pairs_path,
    run_root=SMOKE_ROOT,
    owner="smoke",
    work_dir=Path("/content/ft_work_smoke"),
    resume_tag=RESUME_TAG,
    keep_last_runs=2,
    note="smoke test (가짜 데이터)",
)
if TARGET == "qwen":
    cfg = FinetuneConfig(
        model_config_path=PROJECT_DIR / "configs" / "models" / "qwen3_0_6b.yaml",
        learning_rate=1e-4, lora_rank=16, lora_alpha=32, **common,
    )
else:
    cfg = FinetuneConfig(
        model_config_path=PROJECT_DIR / "configs" / "models" / "arctic_ko.yaml",
        learning_rate=2e-5, **common,
    )

# %%
final_dir = run_finetune(cfg)

"""## 결과 확인 — 아래가 전부 [OK]면 통과"""

from sentence_transformers import SentenceTransformer
from store_search_ai.pipeline.common import load_config

checks = []


def check(name, ok, detail=""):
    checks.append(ok)
    print(f"[{'OK' if ok else 'FAIL'}] {name} {detail}")


files = {p.name for p in final_dir.iterdir()}
manifest = json.loads((final_dir / "model_manifest.json").read_text(encoding="utf-8"))
check("최종 폴더에 manifest/eval_config/ST 설정 존재",
      {"model_manifest.json", "eval_config.yaml", "modules.json", "config_sentence_transformers.json"} <= files,
      sorted(files))
check("LoRA adapter 파일이 없음(merge된 전체 모델)", "adapter_config.json" not in files)
check("중간 체크포인트 폴더 삭제됨", not (SMOKE_ROOT / f"{final_dir.name}.ckpt").exists())
check("partial 폴더 없음", not (SMOKE_ROOT / f"{final_dir.name}.partial").exists())
result = manifest["training_result"]
check("중간 체크포인트가 저장됐었음", result.get("mid_checkpoint_step") is not None or result.get("resumed_from") is not None,
      f"mid_checkpoint_step={result.get('mid_checkpoint_step')} resumed_from={result.get('resumed_from')}")
if RESUME_TAG:
    check("이어서 학습으로 끝남", result.get("resumed_from") is not None, result.get("resumed_from"))
check("loss가 유한함", all(abs(h["loss"]) < 1e6 for h in result["loss_history"]), f"final_loss={result['final_loss']}")
print("  precision:", manifest["precision"], "/ gpu:", manifest["environment"]["gpu"])
print("  serving:", json.dumps(manifest["serving"], ensure_ascii=False))

# 학습된 모델이 베이스 모델과 실제로 달라졌는지(= 학습이 반영돼 저장됐는지), prompt가 살아있는지
base_config = load_config(cfg.model_config_path)
prompt_name = base_config.get("query_prompt_name")
trained = SentenceTransformer(str(final_dir), device="cuda")
base = SentenceTransformer(base_config["model_id"], device="cuda")
texts = ["테스트 질의 3번 매장", "국밥"]
kwargs = {"prompt_name": prompt_name} if prompt_name else {}
a = trained.encode(texts, normalize_embeddings=True, convert_to_tensor=True, **kwargs).float()
b = base.encode(texts, normalize_embeddings=True, convert_to_tensor=True, **kwargs).float()
cos = torch.nn.functional.cosine_similarity(a, b).min().item()
check("학습 후 임베딩이 베이스와 달라짐", cos < 0.9999, f"min cosine={cos:.4f}")
check("pooling 설정이 베이스와 같음", str(trained[1]) == str(base[1]), str(trained[1]))
if prompt_name:
    check("query prompt 유지", trained.prompts.get(prompt_name) == base.prompts.get(prompt_name),
          repr(trained.prompts.get(prompt_name)))
del trained, base
torch.cuda.empty_cache()

print("\n통과" if all(checks) else "\n실패 항목이 있습니다 — 위 로그 전체를 공유해 주세요")
print(f"테스트가 끝나면 Drive {SMOKE_ROOT} 폴더는 통째로 지워도 됩니다.")
