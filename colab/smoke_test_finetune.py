# -*- coding: utf-8 -*-
"""store_search_ai_colab_finetune_smoke_test.ipynb

실제 학습 데이터 없이 **가짜 데이터로 Colab 파이프라인 전체를 GPU에서 한 번 검증**한다.
push 전, 또는 라이브러리 버전/Colab 환경이 바뀌었을 때 돌려서
"학습 → 중간 체크포인트 → 이어서 학습 → merge/저장 → 재로드 검증 → manifest → 체크포인트 삭제
 → **평가(공식 evaluator 채점) → 기준 모델 대비 비교 → manifest에 평가 기록 → 리더보드 → test 차단**"
이 끝까지 되는지 확인한다. 나오는 모델·점수 자체는 쓸모없다(가짜 데이터, 축소 코퍼스).

- 결과는 `runs/finetune_smoke/`(실제 run과 다른 폴더)에만 저장되고, OWNER는 "smoke"로 고정 —
  실제 run의 자동 정리와 절대 섞이지 않는다.
- 테스트는 두 단계:
    1단계: RESUME_TAG = None 으로 실행 → `[체크포인트] ... 저장 완료` 가 찍히면 **런타임 > 실행 중단**
    2단계: 그 로그에 나온 TAG를 RESUME_TAG에 넣고 이 셀부터 다시 실행 → 끝까지 가는지 확인
  (중단 없이 끝까지 가게 두면 재개 테스트만 빠지고 나머지는 전부 검증된다.)

Drive 준비: 로컬에서 `python scripts/pack_for_colab.py` → `colab_upload/project/`를 Drive `store-search-ai/project`로
올리기(학습 데이터는 없어도 됨 — 이 노트북이 가짜 데이터를 만든다. 평가 확인에 corpus·qrels가 필요하므로
`--no-eval-data`로 pack하면 안 됨)
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

from store_search_ai.common.hf_compat import check_environment

check_environment()  # 버전 출력 + 최소 버전 미달·채점 패키지 누락이면 여기서 바로 알려 줌(실제 버전은 기록에도 남음)

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

"""## 평가 파이프라인 확인 — 학습한 모델을 채점까지 (축소 코퍼스, 비공식)

실제 평가는 문서 21만 개를 인코딩하지만, 여기서는 배관 확인용으로 **val 정답에 나온 문서 + 무작위 2,000개**만 쓴다.
점수는 의미가 없고, `official=False`로 저장돼 리더보드·로컬 가져오기(`import_colab_results.py`)에서 자동으로 빠진다.
결과는 `runs/finetune_smoke/` 밑에만 쌓인다(실제 평가 폴더와 섞이지 않음).
"""

# %%
import pandas as pd

from store_search_ai.evaluation.model_evaluation import (
    collect_leaderboard,
    evaluate_model,
    format_report,
    load_eval_inputs,
)

eval_inputs = load_eval_inputs(PROJECT_DIR)
qrels_path = eval_inputs["benchmark_dir"] / "qrels_val.trec"
judged = {line.split()[2] for line in qrels_path.read_text(encoding="utf-8").splitlines() if line.strip()}
corpus = eval_inputs["corpus"]
small_corpus = pd.concat(
    [corpus[corpus["doc_id"].isin(judged)], corpus[~corpus["doc_id"].isin(judged)].sample(2000, random_state=0)]
).reset_index(drop=True)
small_inputs = {**eval_inputs, "corpus": small_corpus}
print(f"[INFO] 축소 코퍼스 {len(small_corpus):,}개 (전체 {len(corpus):,}개)")

SMOKE_RUN_ROOT = SMOKE_ROOT / "model_eval"
SMOKE_EVAL_ROOT = SMOKE_ROOT / "evaluation"
base_eval = evaluate_model(base_config, small_inputs, run_root=SMOKE_RUN_ROOT, eval_root=SMOKE_EVAL_ROOT, official=False)
print(format_report(base_eval["report"]))
del base_eval
torch.cuda.empty_cache()

eval_config = {**load_config(final_dir / "eval_config.yaml"), "model_id": str(final_dir)}
ft_eval = evaluate_model(eval_config, small_inputs, run_root=SMOKE_RUN_ROOT, eval_root=SMOKE_EVAL_ROOT,
                         baseline_tag=base_config["name"], official=False)
report = ft_eval["report"]
print(format_report(report))

check("평가: run.csv 생성", ft_eval["run_path"].exists(), str(ft_eval["run_path"]))
validation = report["run_validation"]
check("평가: val 쿼리 전부 채점(누락·중복 0)",
      validation["missing_queries"] == 0 and validation["duplicate_query_doc_pairs"] == 0,
      f"{validation['queries']}/{validation['expected_queries']}")
check("평가: 기준 모델 대비 비교(p-value) 계산", "comparison" in report)
manifest = json.loads((final_dir / "model_manifest.json").read_text(encoding="utf-8"))
check("평가: 모델 manifest에 평가 기록", any(e["tag"] == report["tag"] for e in manifest["evaluations"]))
board = collect_leaderboard(SMOKE_EVAL_ROOT, "val", include_unofficial=True)
check("리더보드에 기준·학습 모델 둘 다", len(board) >= 2, board["tag"].tolist())
check("비공식 평가는 기본 리더보드에서 빠짐", collect_leaderboard(SMOKE_EVAL_ROOT, "val").empty)
try:
    evaluate_model(eval_config, small_inputs, run_root=SMOKE_RUN_ROOT, eval_root=SMOKE_EVAL_ROOT, split="test",
                   encoder=ft_eval["encoder"], doc_embeddings=ft_eval["doc_embeddings"], official=False)
    check("test split은 allow_test 없이 차단", False)
except ValueError:
    check("test split은 allow_test 없이 차단", True)
del ft_eval
torch.cuda.empty_cache()

"""## 최종 결과"""

# %%
print("\n통과" if all(checks) else "\n실패 항목이 있습니다 — 위 로그 전체를 공유해 주세요")
print(f"테스트가 끝나면 Drive {SMOKE_ROOT} 폴더는 통째로 지워도 됩니다.")
