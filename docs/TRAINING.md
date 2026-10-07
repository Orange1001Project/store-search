# 임베딩 모델 Fine-tuning (Colab)

`docs/MODELING.md`의 zero-shot 비교가 끝난 뒤, 실제로 모델을 우리 데이터에 맞게
학습시키는 단계입니다. 평가 코드는 새로 만들지 않습니다 — fine-tuning으로 나온 모델도
`configs/models/*.yaml`에 등록해서 기존 `14_run_model_eval.py`/`15_score_model_runs.py`로
그대로 채점합니다("run을 채점하는 evaluator는 하나만 둔다", `docs/MODELING.md` 참고).

> **학습만 맡은 팀원은 `docs/TRAINING_TEAM.md`부터 보세요** — 배포된 학습 데이터로 Colab 학습 → 평가 →
> 실험 기록(`results/experiments.csv`)까지의 절차와 팀 규칙만 모아 둔 문서입니다. 이 문서는 그 배경(설계 이유·설정 의미)입니다.

## 사전 조건

train qrels(`benchmark/storesearch_ko_v1/qrels_train.csv`, 없으면
`qrels/full_annotation_v1/qrels_train_provisional.csv`)가 있어야 합니다. `docs/PIPELINE.md` 4절
(`08_make_full_annotation_sheets.py` → 사람이 train 시트 채움 → `09_prepare_full_annotations.py`)
까지 끝나면 준비됩니다 — val/test의 adjudication을 기다릴 필요는 없습니다(train은 애노테이터
1명의 단일 라벨링이라 더 빨리 끝납니다).

## 학습 코드 — Colab 노트북 하나

Colab에서는 **`colab/train_eval.ipynb` 하나**로 모든 모델(Arctic·BGE-M3는 full fine-tuning, Qwen3는 LoRA → 베이스에 merge)을
학습하고 바로 val 채점까지 합니다. 학습·평가 코드가 전부 노트북 셀 안에 있어서(`src/`를 올리지 않음) 팀원이 기법을 셀에서 바로
고쳐 실험하고, 노트북 파일 하나만 다시 올리면 됩니다. 모델별 차이는 설정 셀의 `MODEL_PRESETS` 항목(베이스 모델, prompt, LoRA 여부,
lr 등)뿐이고 학습 루프는 같습니다.

- 학습할 때마다 그 세션에서 실행한 셀 코드 전체가 모델 폴더의 `notebook_code.py`로 저장됩니다(어떤 코드로 만든 모델인지).
- **채점 셀(`7. 평가`)은 공식 evaluator와 같은 로직**이고, `tests/test_train_eval_notebook.py`가 노트북 셀을 실제로 실행해
  `store_search_ai.evaluation.evaluator`와 결과가 같은지 확인합니다. 학습 행 펼치기도 `store_search_ai.training.finetune`과 비교합니다.
- `store_search_ai.training.st_finetune.run_finetune()`은 같은 학습 방식의 로컬 참조 구현입니다(로컬 GPU용).

**라이브러리 버전**: Colab에 미리 깔린 torch·transformers·sentence-transformers·peft·datasets·accelerate를 **그대로** 씁니다
(2026-10 기준 Python 3.13, transformers 5.18, sentence-transformers 5.7, peft 0.21). 예전에는 옛 버전(transformers 4.51,
sentence-transformers 3.4)을 노트북에서 강제로 설치했는데, 그러면 Colab의 huggingface_hub·fsspec까지 내려가 gradio·diffusers·
gcsfs와 충돌하고 Colab이 업데이트될수록 더 어긋났습니다. 노트북이 추가로 설치하는 건 채점용 `ir-measures`·`pytrec-eval-terrier`
뿐입니다. 버전마다 바뀐 API(transformers 5의 `dtype`·`warmup_steps`, sentence-transformers 5의 읽기 전용 `auto_model` 등)는
노트북의 `2. 라이브러리 버전 호환` 셀(로컬은 `store_search_ai.common.hf_compat`)이 맞추고, `check_environment()`가 시작할 때 버전을 출력·점검합니다. 실제로 쓴 버전은
manifest `environment`와 평가 json `library_versions`에 남고 리더보드에도 표시됩니다 — **비교는 같은 버전끼리** 합니다.

**예전 버전(ms-swift)을 버린 이유**: T4는 ms-swift 예제가 전제하는 bf16/flash-attention을 지원하지
않고, ms-swift가 저장하는 LoRA adapter는 merge해도 sentence-transformers 설정(Qwen3의 last-token
pooling, query prompt)이 빠져서 `SentenceTransformer(path)`로 로드하면 **에러 없이 mean pooling으로
로드돼 임베딩이 틀어집니다**. 우리 평가(14번)와 서빙이 전부 sentence-transformers 기준이라 치명적입니다.
또 버전마다 데이터 포맷과 플래그가 바뀌었습니다(`query/response` → `messages/positive_messages`,
`--train_type` → `--tuner_type`).

## 1. 학습 데이터 준비 (로컬, GPU 불필요)

```bash
python scripts/prepare_finetune_dataset.py
```

- train qrels + `queries.csv` + corpus로부터 `data/finetune/train_pairs.jsonl`과
  `train_pairs.meta.json`(어떤 qrels·설정·커밋으로 만들었는지)을 만듭니다. **Colab에는 둘 다 올립니다.**
- 각 줄: `{"query_id", "query", "positives": [...], "negatives": [...]}`
- **positives**: 그 query의 pool에서 `relevance >= binary_relevance_threshold`(기본 2)인 문서 **전부**
  (relevance 높은 순). 예전에는 첫 번째 하나만 써서 학습 예시가 query 수(237개)밖에 안 됐습니다.
- **negatives**: 같은 pool에서 relevance가 그 미만인 문서(최대 `--max-negatives`개, relevance=1인 경계
  사례 우선 — 무작위 negative보다 훨씬 어려운/유용한 negative).
- 텍스트가 완전히 같은 문서(체인점 등)는 한 번만 쓰고, positive와 텍스트가 같은 문서는 negative에서 뺍니다.
- positive가 하나도 없는 query는 제외되고 로그에 개수가 찍힙니다.

학습 쪽(`store_search_ai.training.finetune.expand_training_rows`)에서 (query, positive)마다 한 행으로
펼칩니다. query당 positive는 `max_positives_per_query`(기본 32)개까지 — "한식"처럼 positive가 수백 개인
넓은 query가 학습을 독점하지 않게 하기 위해서입니다. hard negative는 모든 행이
`num_hard_negatives`(기본 3)개로 같아야 해서, 그보다 적은 query는 제외됩니다(개수는 로그와 manifest에 남음).

## 2. Colab에서 학습 (T4 기준)

로컬에서 `python scripts/pack_for_colab.py`로 `colab_upload/data/`(학습 데이터·corpus·queries·val/test qrels +
`data_version.json`: git 브랜치·커밋, 파일별 sha256, 평가 설정)를 만들어 Drive `내 드라이브/store-search-ai/data`로 **한 번** 올리고
(데이터가 바뀔 때만 다시), Colab에서 `colab/train_eval.ipynb`를 열어 설정 셀의 **`OWNER`를 본인 이름(영문 소문자)으로 바꿔서**
실행합니다. 처음엔 `SMOKE=True`로 전체 흐름을 확인합니다(절차는 `docs/TRAINING_TEAM.md`). `HP`의 나머지 값은 팀 공통 기본값입니다 —
바꾼 값은 전부 manifest에 자동으로 남지만, 결과를 서로 비교하려면 합의 없이 바꾸지 마세요.

**작업 방식(요약)** — 자세한 절차는 `docs/TRAINING_TEAM.md` 1~4절, 셀별 코드 설명은 `docs/TRAIN_EVAL_NOTEBOOK.md`.

| 단계 | 어디서 | 무엇을 |
|---|---|---|
| 1. 데이터 올리기 (처음 한 번, 데이터가 바뀔 때만) | 로컬 → Drive | `pack_for_colab.py` → `colab_upload/data/`를 `store-search-ai/data/`로 |
| 2. 노트북 올리기 | Colab | 파일 > 노트북 업로드 → `colab/train_eval.ipynb` → `SMOKE=True`로 `통과` 확인 |
| 3. 실험 반복 | Colab | 설정·기법 수정 → 8. 학습 → 9. 평가 → 10. 리더보드 |
| 3-A. 작은 수정 | Colab에서 바로 | 고친 셀 → 8 → 9 → 10 (세션 유지). 끝나면 노트북을 내려받아 저장소 파일에 덮어쓰기 |
| 3-B. 큰 수정 | VS Code(Claude) | 저장소 `colab/train_eval.ipynb` 수정 → Drive `Colab Notebooks`의 이전 사본 삭제 → 다시 업로드 → 위에서부터 실행 |
| 4. 마무리 | 로컬 | Drive `store-search-ai` 내려받기 → `import_colab_results.py --verify` → 커밋 |

자동으로 처리되는 것:

- **precision**: GPU가 bf16을 하드웨어로 지원하면(L4·A100, compute capability 8 이상) bf16, T4면 fp16 AMP(가중치는 fp32,
  연산만 fp16). `torch.cuda.is_bf16_supported()`는 에뮬레이션까지 True라 T4에서도 True가 나오므로 GPU 세대로 판단합니다(자세히는 6절).
  loss가 NaN/inf가 되면 학습을 멈추고 **Drive에 아무것도 저장하지 않습니다** → lr을 낮추거나 L4/A100 사용.
- **배치**: `NO_DUPLICATES` — 같은 텍스트(같은 query의 다른 positive 행, 공유 negative)가 한 배치에
  두 번 들어가 서로를 오답으로 배우는 일을 막습니다.
- **loss**: 기본 `gist`(GISTEmbedLoss, 베이스 모델이 guide) — 같은 family의 query가 한 배치에 섞이면
  서로의 정답을 오답으로 배우는데("국밥"과 "순대국"), guide가 정답보다 더 비슷하다고 보는 in-batch
  negative를 걸러줍니다. 메모리가 부족하면 `mnrl`. preset에 `target_dimension`이 있으면(qwen3_4b) 그
  차원에서도 성능이 유지되도록 Matryoshka로 감쌉니다.
- **query prompt**: preset(`MODEL_PRESETS`, 저장소 `configs/models/*.yaml`과 같은 값)의 `query_prompt_name` prompt를 학습 때도
  그대로 붙입니다 → 평가/서빙에서도 `prompt_name`만 맞으면 학습 때와 같은 문자열이 붙습니다. preset에 `query_prompt` 문자열이
  있으면(`*_store` 변형의 `STORE_PROMPT`) 그 문자열로 학습하고, 저장되는 모델의 prompt도 그 문자열로 바뀝니다.

T4(15GB)에서 모델별 설정:

| 모델 | 설정 |
|---|---|
| arctic_ko / bge_m3 | 기본값(batch 32, mini_batch 16). OOM이면 mini_batch 8 → 그래도 안 되면 batch 16 또는 `loss="mnrl"` |
| qwen3 0.6B | 기본값(LoRA r=16, lr 1e-4, fp32 베이스, batch 32, mini_batch 16) |
| qwen3 4B | preset 기본값(fp16 베이스, batch 8, mini_batch 4, `mnrl`). fp16 overflow로 NaN이 나면 L4/A100 필요 |
| qwen3 8B | T4 불가 |

**mini_batch_size (GradCache)**: batch 32 × (query + positive + negative 3) = 한 step에 160문장을 한꺼번에 역전파하면 T4에서
OOM이 납니다. `mini_batch_size < batch_size`면 Cached loss(`CachedGISTEmbedLoss`/`CachedMultipleNegativesRankingLoss`)를 써서
batch 전체의 임베딩은 grad 없이 먼저 구하고 역전파만 mini_batch씩 나눠 합니다 — in-batch negative·loss·gradient는 같아서
**결과는 batch 32와 같고 메모리만 줄어듭니다**(약 1.3~1.5배 느림). 그래서 run끼리 비교할 때 mini_batch는 달라도 됩니다.

### 중간 체크포인트 (한 번만) + 이어서 학습

학습 step의 **절반 지점에서 딱 한 번** Drive `runs/finetune/<TAG>.ckpt/checkpoint-N/`에 체크포인트(모델 +
optimizer/scheduler 상태)를 저장합니다. 매 epoch마다 쌓지 않는 이유는 Drive 용량 때문입니다.

- **Colab 연결이 끊기면**: 노트북 `1. 설정`의 `RESUME_TAG`에 그 run의 TAG(`.ckpt` 앞부분)를 넣고, **나머지 설정은
  처음과 똑같이** 둔 채 다시 실행하면 checkpoint-N부터 이어서 학습합니다. 설정이나 `train_pairs.jsonl`이
  처음과 다르면(`.ckpt/run_config.json`과 비교) 이어 붙이지 않고 거부합니다 — 다른 설정의 학습이 섞인
  모델이 나오면 manifest를 믿을 수 없게 되기 때문입니다(`note`, `keep_last_runs`, `save_mid_checkpoint`, `resume_tag`,
  `mini_batch_size`만 달라도 됨 — OOM이 나서 mini_batch를 줄여 이어 하는 것은 허용). 끊긴 시점별 절차는 `docs/TRAINING_TEAM.md` 4절.
- **절반 지점 전에 끊기면** 체크포인트가 없으니 처음부터 다시 돌립니다(`.ckpt` 폴더는 지워도 됨).
- **최종 모델 저장이 성공하면 `.ckpt` 폴더는 자동으로 지웁니다.** 끝나지 않은 run의 `.ckpt`는 자동 정리
  대상이 아니라서, 이어서 학습할 게 아니면 Drive에서 직접 지우세요.
- **크기**: LoRA(Qwen3)는 수십 MB, full fine-tuning(Arctic/BGE)은 fp32 가중치 + Adam 상태라 **약 7GB**입니다.
  학습 도중에는 Drive에 그만큼 여유가 필요합니다. 여유가 없으면 `SAVE_MID_CHECKPOINT = False`
  (끊기면 처음부터 다시).

## 3. 저장 규칙 — Drive에 남는 건 최종 모델만

`runs/finetune/<TAG>/` 하나에 전부 들어갑니다(`TAG` = `{베이스모델}_ft_{OWNER}_{YYYYMMDD_HHMM}`, UTC):

```
runs/finetune/bge_m3_ft_jisu_20260928_0307/
  model.safetensors ...        # merge된 전체 모델, fp16 (fp32의 절반 용량; fp16에서 임베딩이 달라지면 float32 — manifest serving.saved_dtype)
  modules.json, 1_Pooling/ ... # sentence-transformers 설정(pooling/prompt/normalize) — 그대로 로드 가능
  model_manifest.json          # 5절
  eval_config.yaml             # configs/models/<TAG>.yaml로 복사해서 쓰는 평가 설정
  notebook_code.py             # 이 모델을 만든 세션에서 실행한 노트북 셀 코드 전체(로컬 run_finetune은 code_snapshot.zip)
```

- 저장은 `<TAG>.partial/`에 먼저 하고, **다시 로드해서 임베딩이 메모리의 모델과 같은지 검증**하고
  manifest까지 쓴 뒤에야 `<TAG>/`로 이름을 바꿉니다. `.partial`이 남아 있으면 중간에 끊긴 것이니 지웁니다.
- 저장이 끝나면 **같은 OWNER·같은 베이스 모델의 run은 최신 3개(`keep_last_runs`)만 남기고 지웁니다.**
  다른 팀원의 run, 다른 베이스 모델의 run, `.partial`/`.ckpt` 폴더는 건드리지 않습니다.
- **서비스 후보로 남길 run은 그 폴더에 빈 파일 `KEEP`을 만듭니다**(Drive 화면에서는 빈 파일을 못 만들어서,
  노트북 `13. KEEP` 셀의 `(FINETUNE_DIR / "<TAG>" / "KEEP").touch()` 한 줄로). KEEP이 있는 run은 지우지 않고
  3개 개수에도 세지 않습니다. Colab에서 val 점수(9·10번)를 보고 고른 run에 **Drive를 내려받기 전에** KEEP을 붙입니다 —
  `import_colab_results.py`는 KEEP한 run의 모델만 가져옵니다(`--models <TAG>`로 지정한 run은 KEEP에 더해서 가져옴).
- Drive에서 지운 폴더는 Drive 휴지통으로 갑니다. 용량을 바로 확보하려면 휴지통도 비우세요.

## 4. 평가 — Colab에서 바로, 마지막에 로컬로 가져오기

학습 노트북은 학습 셀 다음에 **평가 셀**이 있어서, 학습이 끝나면 같은 노트북에서 val을 채점하고 기준 zero-shot 모델 대비
Δ·p-value와 리더보드를 바로 보여 줍니다. 채점 코드는 노트북 `7. 평가` 셀(`evaluate()`·`score_run()`)에 들어 있는 **복제 구현**이고,
로컬 공식 evaluator(13번, `store_search_ai.evaluation.evaluator`)와 결과가 같은지를 `tests/test_train_eval_notebook.py`가 노트북 셀을
실제로 실행해 확인합니다(가져올 때 `import_colab_results.py --verify`도 로컬에서 다시 채점). 결과는 Drive `runs/model_eval/`·
`runs/evaluation/`에 쌓이고 모델 폴더의 `model_manifest.json` `evaluations`에도 기록됩니다. 그래서 **학습 → 평가 → 수정 → 다시 학습을
Colab 안에서 반복**합니다.

실험이 다 끝나면 Drive의 `store-search-ai` 폴더를 내려받아:
```bash
python scripts/import_colab_results.py --drive-dir <내려받은 store-search-ai> --verify
```
→ `results/model_eval/`(run CSV), `artifacts/evaluation/storesearch_ko_v1/`(평가 json), `results/experiments.csv`(실험 기록표, 평가마다 한 줄),
`results/finetune_runs/<TAG>/`(모든 학습 run의 manifest·eval_config·notebook_code), KEEP한 run의 `models/<TAG>/` + `configs/models/<TAG>.yaml`로
정리하고, `--verify`가 로컬에서 다시 채점해 Colab 점수와 같은지 확인합니다. 절차는 `docs/TRAINING_TEAM.md` 9절.

로컬 GPU로 평가하는 기존 방법(`14_run_model_eval.py --model-config configs/models/<TAG>.yaml` → `15_score_model_runs.py`)도
그대로 쓸 수 있습니다(같은 evaluator).

## 5. model_manifest.json — 서비스에 가져다 쓸 체크포인트 추적

가중치만 있으면 몇 달 뒤엔 "이 모델이 정확히 무엇으로, 어떤 데이터로, 어떤 설정으로 학습됐고 성능이
어땠는지" 알 방법이 없습니다. 노트북의 `train_model()`(로컬은 `run_finetune()`)이 학습 직후 아래를 기록하고, 평가할 때마다 `evaluations`가 쌓입니다:

| 키 | 내용 |
|---|---|
| `tag`, `owner`, `base_model_id`, `base_model_config`, `framework`, `precision` | 무엇을 누가 어떻게 |
| `hyperparameters` | 노트북 `HP` 전체 + note·resume_tag·save_mid_checkpoint(로컬 `run_finetune()`은 `FinetuneConfig` 전체) |
| `training_data` | jsonl 경로·sha256, 펼친 행 통계, `prepare_meta`(qrels 경로·sha256·final/provisional, template, threshold, 데이터를 만든 git commit) |
| `training_result` | 학습 시간, step 수, 최대 GPU 메모리, loss 기록, 중간 체크포인트 step, 이어서 학습했는지(`resumed_from`) |
| `serving` | **서빙이 그대로 따라야 할 값**: document template, query prompt 이름·원문, 임베딩 차원, normalize, cosine, max_seq_length, 실제 저장 dtype |
| `environment` | 라이브러리 버전·GPU |
| `code` | 학습에 실제로 쓴 노트북 셀 코드 사본(모델 폴더의 `notebook_code.py`)과 그 해시 — 셀을 고쳐 가며 실험해도 정확한 코드가 남음(로컬 `run_finetune()`은 `code_snapshot.zip` + git 커밋) |
| `data_version` | `pack_for_colab.py`가 적은 데이터의 git 브랜치·커밋, 파일별 sha256 — Colab엔 .git이 없어서 사람이 커밋 번호를 적지 않아도 되게 |
| `evaluations` | 평가할 때마다 추가되는 split별 지표(Colab은 노트북 `evaluate()`, 로컬은 14번) |

모델 가중치 폴더(`models/<TAG>/`)는 `.gitignore` 대상이라 git에는 안 올라갑니다 — 서비스 후보는 폴더를 통째로 공유 스토리지에 둡니다.
대신 `import_colab_results.py`가 모든 run의 manifest·eval_config·notebook_code를 `results/finetune_runs/<TAG>/`로, 평가마다 한 줄을
`results/experiments.csv`(실험 기록표)로 저장소에 남깁니다.
서빙 인프라(API, ANN 인덱스 등)는 아직 이 저장소 범위 밖입니다 — 이 매니페스트의 `serving`이
"서빙이 학습·평가와 똑같이 인코딩하려면 무엇을 맞춰야 하는지"의 단일 기준입니다.

## 6. 정밀도(fp32 · fp16 · bf16) 정리

### 세 가지 숫자 형식

| 형식 | 비트 | 표현 범위(최댓값) | 정밀도(유효 자릿수) | 특징 |
|---|---|---|---|---|
| **fp32** (float32) | 32 | 약 3.4×10³⁸ | 약 7자리 | 기준. 정확하지만 메모리 2배·느림 |
| **fp16** (float16) | 16 | **65,504** | 약 3~4자리 | 범위가 좁아 큰 값은 `inf`로 넘침(→ NaN). 학습 땐 loss scaling 필요 |
| **bf16** (bfloat16) | 16 | fp32와 같음(약 3.4×10³⁸) | 약 2~3자리 | 범위가 넓어 넘침이 거의 없음. 대신 자릿수가 fp16보다 적음 |

임베딩 학습·검색에서는 반 정밀도(fp16/bf16)로도 점수 차이가 거의 없어서, 속도·메모리를 위해 "가중치는 fp32로 두고 연산만 반 정밀도로"
하는 **AMP(mixed precision)**를 씁니다. fp16 AMP는 작은 gradient가 0이 되지 않게 loss를 키웠다 되돌리는 GradScaler를 같이 쓰고, bf16 AMP는
범위가 넓어서 필요 없습니다.

### GPU별로 무엇을 쓰나

| GPU (compute capability) | fp16 | bf16 | 노트북이 고르는 학습 정밀도 |
|---|---|---|---|
| **T4** (7.5, 무료 Colab) | 텐서코어 가속 | **하드웨어 없음** — torch가 bf16 텐서는 만들 수 있지만 가속을 못 받아 느림 | **fp16** |
| **L4** (8.9) / **A100** (8.0) | 가속 | 가속 | **bf16** (넘침 위험이 적어 더 안전) |

**주의 — `torch.cuda.is_bf16_supported()`**: 최신 torch에서는 이 함수가 "에뮬레이션으로라도 bf16 텐서를 만들 수 있는가"까지 보고 True를 돌려줘서
**T4에서도 True**가 나옵니다. 2026-10-07 이전 노트북은 이 함수로 판단해서 T4에서 bf16(하드웨어 가속 없음)으로 학습했습니다. 지금은 GPU 세대
(compute capability 8 이상이면 bf16)로 판단합니다(노트북 `training_precision()`, 로컬 `st_finetune._pick_precision`).

### 노트북에서 dtype이 정해지는 곳

| 어디 | 값 | 이유 |
|---|---|---|
| **학습 연산**(`precision`, Trainer `fp16`/`bf16`) | T4 fp16 AMP, L4·A100 bf16 AMP | 위 표. manifest `precision`에 기록 |
| **베이스 가중치**(`HP["base_dtype"]`) | 0.6B·Arctic·BGE: float32 / 4B: float16 | 4B는 fp32면 약 16GB라 T4(15GB)에 안 올라감 |
| **LoRA 파라미터** | 항상 float32 | fp16 파라미터는 GradScaler가 unscale하지 못해 에러(4B) |
| **GIST guide 모델** | 학습 정밀도 계열(T4 fp16, L4·A100 bf16) | 학습하지 않고 유사도만 계산 → 반 정밀도로 메모리 절약 |
| **저장**(`HP["save_dtype"]`) | float16 (안 맞으면 float32) | 용량 절반. 저장 후 다시 불러와 **학습된 모델(fp32)과 임베딩 비교**(cosine ≥ 0.999), 다르면 학습된 fp32 가중치로 다시 저장. 실제 값은 manifest `serving.saved_dtype` |
| **평가 로드**(`eval_dtype()`) | `torch_dtype`(4B float16), 없으면 GPU **`EVAL_DTYPE`(기본 float16)**, CPU float32 | 아래 "평가 dtype" |
| **검색·채점** | numpy float32 | 내적·정규화는 항상 fp32 |

### 평가 dtype을 고정한 이유

transformers 5는 dtype을 지정하지 않으면 `dtype="auto"`, 즉 **모델 파일에 적힌 dtype**으로 올립니다. 그래서 고정 전에는:
- 기준 zero-shot Qwen3(모델 config가 bf16) → **bf16**으로 채점(T4에서는 느린 bf16)
- 학습 모델(fp16으로 저장) → **fp16**으로 채점

이렇게 같은 리더보드 안에서 정밀도가 달라 Δ에 정밀도 차이가 섞였습니다. 지금은 **모든 모델을 같은 dtype으로** 올립니다:
preset에 `torch_dtype`이 있으면(4B) 그 값, 없으면 GPU에서는 `1. 설정`의 `EVAL_DTYPE`(기본 **float16**), CPU에서는 float32
(노트북 `eval_dtype()`, 로컬 `SentenceTransformerEncoder` 같은 규칙).

- **왜 float16인가 — 평가 시간**: 평가 시간의 대부분은 문서 21만 개 인코딩입니다. T4는 fp16 텐서코어가 있어 fp32보다 몇 배 빠르고, 기준·학습
  모델을 같은 fp16으로 채점하면 비교 조건도 같습니다. 학습 모델 저장 검증에서 fp16과 fp32 임베딩이 cosine 0.999 이상으로 같았습니다.
- **같이 줄인 것**: 평가 batch `EVAL_BATCH_SIZE`(기본 256 — 문서가 평균 24자라 32개씩 넣으면 GPU를 거의 놀림), 같은 텍스트 문서(약 6%)는 한 번만
  인코딩. 둘 다 결과는 그대로이고 시간만 줄어듭니다.
- **안전장치**: 임베딩에 NaN/inf가 나오면(fp16 넘침) 평가를 멈추고 `EVAL_DTYPE = "float32"`로 바꾸라고 안내합니다. 평가 중 OOM이면
  `EVAL_BATCH_SIZE`를 128/64로.
- 평가 json의 `eval_dtype`과 리더보드 `eval_dtype` 열에 기록되며, **값이 다른 결과끼리는 비교하지 않습니다**(비어 있으면 고정 전 결과 → 다시 평가).

### 학습 뒤 저장 검증과 관련된 함정

fp16/bf16 AMP로 학습하면 accelerate가 모델의 forward에 autocast를 덧씌우고 학습이 끝나도 그대로 둡니다. 이 상태로 "메모리 속 모델 vs 저장본"을
비교하면 서로 다른 정밀도로 계산돼 멀쩡한 저장본도 불일치로 나옵니다. 그래서 저장 전에 `extract_model_from_parallel(model,
keep_fp32_wrapper=False)`로 그 덮개를 벗기고, 저장 dtype으로 바꾸기 **전** 임베딩을 기준으로 비교합니다(NaN은 불일치로 판정).

### 비교·재개 규칙

- **학습 정밀도가 같은 run끼리** 비교합니다(manifest `precision`, 실험 기록표 `precision` 열). fp16 AMP와 bf16 AMP 결과는 보통 차이가 작지만
  0은 아닙니다.
- **평가 dtype이 같은 결과끼리** 비교합니다(리더보드 `eval_dtype`).
- **이어서 학습(`RESUME_TAG`)은 처음과 같은 종류의 GPU에서만** 됩니다 — `run_config.json`에 precision이 기록되고 다르면 거부합니다
  (T4로 시작한 run을 L4에서 이어 붙이면 앞 절반은 fp16, 뒤 절반은 bf16인 모델이 됨).
- 서비스는 fp16·fp32 어느 쪽으로 올려도 됩니다(저장 검증 cosine ≥ 0.999). 평가는 GPU fp16(`eval_dtype`)으로 했습니다.

### 2026-10-07 이전에 T4에서 학습한 run

- **모델은 유효합니다 — 다시 학습할 필요 없음.** bf16 AMP는 A100에서 쓰는 것과 같은 정상적인 학습 방식이고, T4에서는 하드웨어 가속이 없어
  **느렸을 뿐** 계산 결과가 틀린 것이 아닙니다. 저장 검증(학습된 모델과 저장본 임베딩 일치)도 통과했습니다. manifest `precision`은 `bf16`으로
  정확히 기록돼 있습니다.
- **평가는 다시 하세요.** 그때 평가는 기준(bf16)과 학습 모델(fp16)의 정밀도가 달랐습니다. Drive `runs/model_eval/<기준이름>/`을 지우고
  `EVAL_RUN_TAG = "<TAG>"`로 다시 실행하면 둘 다 같은 `eval_dtype`(GPU fp16)으로 채점됩니다.
- 이후 T4에서 새로 학습하는 run은 fp16 AMP라 정밀도가 다릅니다. 이 run을 기준(baseline)으로 계속 쓸 거면 비교 때 이 점을 적어 두고,
  깔끔한 비교가 필요하면 같은 설정으로 한 번 다시 학습해 fp16 baseline을 만드는 것도 방법입니다(필수는 아님).

## 재현성 메모

`data/finetune/train_pairs.jsonl`은 qrels_train + corpus + queries.csv로부터 결정적으로
재생성되는 파생 파일입니다. train qrels가 갱신되면(추가 애노테이션 등)
`prepare_finetune_dataset.py`를 다시 돌리고 jsonl과 meta.json을 같이 다시 올린 뒤 Colab 학습도 다시 하면 됩니다.
seed는 고정(20260831)이지만 GPU 종류·precision(fp16/bf16)이 다르면 결과가 조금 달라질 수 있으므로,
비교는 manifest의 `precision`/`environment.gpu`가 같은 run끼리 하는 것이 원칙입니다.

평가도 같은 원칙입니다: 평가 dtype(`eval_dtype`)이 같은 결과끼리만 비교합니다(6절 — GPU 기본 fp16, 4B는 preset의 float16).
