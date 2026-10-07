# `colab/train_eval.ipynb` 코드 해설

노트북 셀을 위에서부터 하나씩 **무엇을 하는지 → 핵심 코드 → 왜 이렇게 했는지 → 고칠 때 주의점** 순서로 정리한 문서입니다.
작업 절차(올리기·실행 순서·기록)는 `docs/TRAINING_TEAM.md`, 학습 설계 배경은 `docs/TRAINING.md`를 보세요.

> 표기: `[n]`은 노트북에서 위에서 n번째(0부터) 셀, "1. 설정"처럼 번호가 붙은 것은 노트북의 마크다운 제목입니다.
> 셀 맨 첫 줄에 `# @cell 이름`이 있는 셀(settings, compat, rows, runs, eval)은 `tests/test_train_eval_notebook.py`가 이름으로 찾아
> 실제로 실행해 보는 셀입니다 — **이 첫 줄은 지우지 마세요.**

---

## 0. 한눈에 보기

### 셀 구성과 실행 흐름

| 셀 | 제목 | 종류 | 하는 일 | 수정 |
|---|---|---|---|---|
| [0] | (소개) | 설명 | 사용법 요약 | – |
| [1] | GPU 확인 | 실행 | GPU 이름·메모리 출력 | 안 함 |
| [2] | 설치 | 실행 | torchao 제거, 메모리 설정, 채점 라이브러리 설치 | 안 함 |
| [3] | Drive 연결 | 실행 | `/content/drive` 마운트 | 안 함 |
| [5] | **1. 설정** | 값 정의 | 누가·무슨 모델·어떤 설정으로 + 경로 | **자주** |
| [7] | 2. 버전 호환 | 함수 정의 | 라이브러리 버전 차이 흡수 | 거의 안 함 |
| [8] | (환경 점검) | 실행 | 버전 출력·최소 버전 확인 | 안 함 |
| [10] | 3. 데이터 | 실행 | Drive `data/`에서 corpus·queries·정답·학습 데이터 로드 | 안 함 |
| [12] | **4. 학습 행** | 함수 정의 | 학습 데이터 → (query, positive, negatives) 행 | **기법 실험** |
| [14] | **5. 모델·loss** | 함수 정의 | 모델 로드·LoRA·loss 구성 | **기법 실험** |
| [16] | 6-a. run 관리 | 함수 정의 | TAG, 체크포인트 찾기, 오래된 run 정리, 코드 사본 | 거의 안 함 |
| [17] | 6-b. 학습 루프 | 함수 정의 | `train_model`(학습→저장→검증→기록), `save_verified` | Trainer 인자만 |
| [19] | **7. 평가** | 함수 정의 | 인코딩·검색·채점·리더보드 | **절대 안 함** |
| [21] | 8. 학습 | 실행 | `train_model(...)` 호출 | 안 함 |
| [23] | 9. 평가 | 실행 | 기준 zero-shot + 학습 모델 val 채점 | 안 함 |
| [25] | 10. 리더보드 | 실행 | 평가 전부를 nDCG@10 순으로 | 안 함 |
| [27] | 11. zero-shot 표 | 실행 | 여러 모델 한 번에 평가 | 목록만 |
| [29] | 12. SMOKE 확인 | 실행 | 전체 흐름 자동 점검 | 안 함 |
| [31] | 13. KEEP | 실행 | 남길 run 표시 | TAG만 |
| [33] | 14. test | 실행 | 최종 후보만 test 채점 | 안 함 |

**정의 셀과 실행 셀**: [7]·[12]·[14]·[16]·[17]·[19]는 함수만 정의하고 아무것도 실행하지 않습니다. 실제 일은 [21] 이후 셀이
그 함수를 부를 때 일어납니다. 함수들은 `RUN_DIR`, `corpus`, `RECORDS` 같은 전역 값을 **호출하는 순간** 읽기 때문에, 설정([5])이나
데이터([10])를 다시 실행하면 함수 셀은 다시 실행하지 않아도 새 값이 적용됩니다.

### 데이터 흐름

```
Drive data/ ──[10]──▶ corpus(문서 21만) · queries(active: train 237·val 136·test 175, 평가는 val/test만) · QRELS(정답 경로) · RECORDS(학습 query 237개)
                                                          │
RECORDS ──[12] expand_training_rows──▶ rows 7,270행 {anchor, positive, negative_1..3}
                                                          │
preset·HP ──[14] build_model / build_loss──▶ model(+LoRA) · loss(GIST/MNRL, Cached)
                                                          │
[17] train_model ──▶ Trainer 학습 ──▶ merge ──▶ save_verified ──▶ Drive runs/finetune/<TAG>/
                                                          │
[19] evaluate ──▶ corpus·val query 인코딩 ──▶ exact 검색 top100 ──▶ run.csv ──▶ score_run(채점) ──▶ evaluation.json
                                                          │
[19] leaderboard ──▶ Drive runs/evaluation/*.json 전부 모아 표
```

### Drive에 생기는 파일

| 경로 (`store-search-ai/` 아래) | 만드는 곳 | 내용 |
|---|---|---|
| `runs/finetune/<TAG>/` | `train_model` | 최종 모델(sentence-transformers 형식) + `model_manifest.json` + `eval_config.yaml` + `notebook_code.py` |
| `runs/finetune/<TAG>.ckpt/` | 학습 중 | 중간 체크포인트 1개 + `run_config.json`. 학습이 끝나면 자동 삭제 |
| `runs/finetune/<TAG>.partial/` | 저장 중 | 저장·검증이 끝나기 전 임시 이름. 검증 통과 후 `<TAG>`로 이름 변경 |
| `runs/model_eval/<이름>/run_<template>_<split>.csv` | `evaluate` | 검색 결과(query별 top 100) |
| `runs/evaluation/<이름>_<template>_<split>_evaluation.json` | `evaluate` | 지표·신뢰구간·기준 대비 비교 |
| `runs/evaluation/..._per_query.csv` | `evaluate` | 쿼리별 지표 |
| `runs_smoke/...` | `SMOKE=True` | 위와 같은 구조, 비공식 |

TAG 형식: `<모델이름>_ft_<OWNER>_<UTC 날짜>_<시각>` (예: `qwen3_embedding_0_6b_ft_kse1_20261006_0647`).

---

## [1] GPU 확인

```python
print("CUDA:", torch.cuda.is_available())
print(torch.cuda.get_device_name(0), ... total_memory ...)
```
GPU 종류에 따라 학습 정밀도가 정해집니다: **T4 → fp16**, L4/A100 → bf16(더 빠르고 NaN 위험이 적음). bf16은 GPU 세대(compute capability 8 이상)로
판단합니다 — `torch.cuda.is_bf16_supported()`는 에뮬레이션까지 True라 T4에서도 True가 나와 쓰지 않습니다. GPU가 없으면 학습이 사실상 불가능하니
런타임 유형을 바꾸라는 경고를 냅니다.

## [2] 설치

| 줄 | 이유 |
|---|---|
| `pip uninstall -y torchao` | Colab 기본 torchao 0.10이 있으면 peft 0.21이 "0.16 이상 필요" ImportError를 냄. 이 노트북은 torchao를 안 씀 |
| `os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")` | GPU 메모리 조각화로 인한 OOM 완화. **torch가 GPU를 처음 쓰기 전에** 설정돼야 효과가 있어 맨 앞에 둠 |
| `pip install ir-measures==0.4.3 pytrec-eval-terrier==0.5.10` | 공식 evaluator와 같은 채점 라이브러리(버전 고정 — 채점 결과가 바뀌면 안 되므로) |

transformers·sentence-transformers·peft 등은 **설치하지 않습니다**(Colab 기본 버전 사용). 예전처럼 특정 버전으로 내리면
huggingface_hub·fsspec까지 내려가 Colab 기본 패키지와 충돌했습니다.

## [3] Drive 연결

`drive.mount("/content/drive")` — 이후 모든 경로는 `/content/drive/MyDrive/store-search-ai/` 아래입니다. Colab 세션이 끝나도
Drive에 쓴 결과(모델·평가)는 남습니다.

---

## [5] 1. 설정 `# @cell settings`

### 실행 스위치

| 변수 | 기본 | 의미 |
|---|---|---|
| `OWNER` | `""` | **필수**. run 이름과 자동 정리 범위(내 run만 정리)에 쓰임. 정규식 `[a-z][a-z0-9]{1,15}` |
| `MODEL` | `"qwen3_0_6b"` | `MODEL_PRESETS`의 키 |
| `NOTE` | `""` | 기본값에서 바꾼 것 한 줄 → manifest `hyperparameters.note` |
| `SMOKE` | `False` | `True`면 가짜 학습 데이터·축소 코퍼스, 결과는 `runs_smoke/`, 비공식 표시 |
| `RESUME_TAG` | `None` | 끊긴 run을 이어 학습할 때 그 TAG |
| `SAVE_MID_CHECKPOINT` | `True` | 학습 절반에서 Drive에 체크포인트 1회 |
| `EVAL_RUN_TAG` | `None` | 학습 없이 기존 run만 평가 |
| `FINAL_TEST` | `False` | test 채점(최종 후보 확정 후에만) |

### `MODEL_PRESETS` — 모델별 고정값

각 항목의 키:

| 키 | 쓰는 곳 | 설명 |
|---|---|---|
| `name` | 결과 폴더·리더보드 이름 | 저장소 `configs/models/*.yaml`의 `name`과 같아야 로컬로 가져올 때 연결됨 |
| `model_id` | 모델 로드 | Hugging Face 모델 ID |
| `query_prompt_name` | 학습·평가·서빙 | 모델에 내장된 prompt 이름(Qwen3 `"query"`, Arctic `"query"` = `"query: "` 접두어). `None`이면 prompt 없음 |
| `query_prompt` | 〃 | prompt 문자열을 직접 지정(`*_store` 변형 — `STORE_PROMPT`) |
| `batch_size` | 평가 인코딩 | 평가 때 한 번에 인코딩하는 문장 수 |
| `target_dimension` | 평가·서빙·Matryoshka | 4B는 2560차원 중 앞 1024차원만 사용 |
| `torch_dtype` | 평가 로드 | 4B는 T4 메모리 때문에 float16으로 로드 |
| `train` | `HP` 기본값 | `lora_rank`(None=full FT), `learning_rate`, `base_dtype`, `batch_size`, `loss`, `mini_batch_size` |

모델별로 다른 이유:
- **Arctic·BGE-M3**(XLM-RoBERTa large, 5.7억 파라미터): full fine-tuning, lr 2e-5(일반적인 encoder 미세조정 값).
- **Qwen3-0.6B**: LoRA r=16, lr 1e-4(LoRA는 바뀌는 파라미터가 적어 lr을 크게), fp32 베이스.
- **Qwen3-4B**: T4에 올리려고 fp16 베이스, batch 8, MNRL(GIST는 guide 모델을 하나 더 올려야 해서 메모리 부족), Matryoshka 1024.

새 모델을 시험하려면 여기에 항목을 하나 추가하고 `MODEL`을 그 키로 바꾸면 됩니다.

### `HP` — 학습 설정 (manifest에 그대로 기록)

| 키 | 기본 | 설명 · 바꿀 때 |
|---|---|---|
| `num_epochs` | 2 | 데이터 전체를 몇 번 보나. 작은 데이터에서 크게 하면 과적합 |
| `batch_size` | preset | 한 step의 행 수 = **in-batch negative 수**. 대조학습은 클수록 유리하지만 메모리 증가 → 결과에 영향 |
| `mini_batch_size` | preset | GradCache로 GPU에 한 번에 올리는 문장 수. **결과에 영향 없음**(메모리·속도만). OOM이면 절반 |
| `learning_rate` | preset | |
| `warmup_ratio` | 0.1 | 처음 10% step 동안 lr을 0에서 올림 |
| `weight_decay` | 0.01 | |
| `max_seq_length` | 128 | 문서 평균 24자라 충분 |
| `num_hard_negatives` | 3 | 행마다 붙는 hard negative 수. 학습 데이터에 query당 최대 8개. 7 이상이면 negative가 적은 query가 빠짐 |
| `max_positives_per_query` | 32 | query당 positive 상한(넓은 query 독점 방지) |
| `loss` | preset | `"gist"` / `"mnrl"` |
| `lora_rank`·`lora_alpha`·`lora_dropout` | preset·32·0.05 | LoRA 크기. `lora_rank=None`이면 full FT |
| `base_dtype` | preset | 학습할 때 베이스 모델 dtype |
| `save_dtype` | float16 | 저장 dtype(용량 절반). 저장 후 임베딩이 달라지면 자동으로 float32로 다시 저장 |
| `seed` | 20260831 | 재현용 |
| `keep_last_runs` | 3 | 내 run 중 같은 모델 최신 N개만 Drive에 남김 |

### 경로

```python
DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
DATA_DIR = DRIVE_ROOT / "data"
RUNS = DRIVE_ROOT / ("runs_smoke" if SMOKE else "runs")
FINETUNE_DIR, RUN_DIR, EVAL_DIR = RUNS / "finetune", RUNS / "model_eval", RUNS / "evaluation"
WORK_DIR = Path("/content/ft_work")      # 체크포인트를 안 쓸 때 Trainer 임시 폴더(로컬 디스크)
OFFICIAL = not SMOKE
```
`SMOKE`에 따라 결과 폴더 전체가 갈라지므로 SMOKE 결과가 실제 리더보드에 섞이지 않습니다. 마지막에 `OWNER` 형식을 검사합니다
(SMOKE면 비어 있어도 `"smoke"`로 채움).

---

## [7] 2. 라이브러리 버전 호환 `# @cell compat`

Colab 라이브러리가 업데이트돼도 노트북이 돌도록 버전 차이를 한곳에서 흡수합니다.

| 함수 | 하는 일 | 배경 |
|---|---|---|
| `version_tuple(pkg)` | `"5.18.0+cu"` → `(5, 18, 0)` | 버전 비교용 |
| `library_versions()` | 주요 라이브러리 버전 dict | manifest·평가 json의 `libs`로 기록 |
| `check_environment()` | 최소 버전 미달·채점 라이브러리 누락이면 에러, 확인 안 된 메이저 버전이면 경고 | |
| `dtype_kwargs(dtype)` | `{"dtype": …}` 또는 `{"torch_dtype": …}` | transformers 4.56부터 `torch_dtype` → `dtype` |
| `set_transformer_model(module, model)` | sentence-transformers 안의 HF 모델 교체 | ST5에서 `auto_model`이 읽기 전용 → `.model`에 대입 |
| `warmup_kwargs(cls, ratio)` | `warmup_ratio` 또는 `warmup_steps` | transformers 5에서 `warmup_ratio` 삭제, `warmup_steps`에 0~1 비율을 넣으면 비율로 해석 |
| `batch_samplers()` | `BatchSamplers` 위치 | ST5에서 모듈 이동 |
| `losses_module()` | loss 모듈 위치 | ST5에서 모듈 이동 |
| `embedding_dimension(model)` | 임베딩 차원 | ST5에서 메서드 이름 변경 |

## [8] 환경 점검

`VERSIONS = check_environment()` — `[환경] torch=…, transformers=…` 출력. 여기서 에러가 나면 설치 셀이 안 돌았거나 Colab 환경이 바뀐 것.

---

## [10] 3. 데이터 불러오기

```python
DATA_VERSION = json.loads((DATA_DIR / "data_version.json").read_text())   # pack_for_colab.py가 기록
EVAL_SETTINGS = DATA_VERSION["evaluation"]          # bootstrap 10000회, seed — 공식 설정과 같은 값
corpus = pd.read_parquet(DATA_DIR / DATA_VERSION["corpus_file"])          # 문서(가맹점) 전체
queries = ...status == "active"...                   # val/test 평가 query
QRELS = {"val": .../qrels_val.trec, "test": .../qrels_test.trec}          # 정답(경로만)
```

- **실제 데이터**(`SMOKE=False`): `train_pairs.jsonl`의 sha256이 `train_pairs.meta.json`의 값과 다르면 멈춥니다(학습 데이터와 그 설명서가
  서로 다른 버전으로 올라간 사고 방지).
- **SMOKE**: 코퍼스를 "val 정답이 있는 문서 + 무작위 2,000개"로 줄이고(약 8,500개), 학습 데이터는 가짜 query 40개 × positive 4개 = 160행을
  `/content/smoke_train_pairs.jsonl`에 만들어 씁니다(10 step 학습, 중간 체크포인트는 5 step).

학습 데이터 한 줄의 형식:
```json
{"query_id": "q_가방_01", "query": "가방",
 "positives": ["가맹점명: 찬스가방 / 취급품목: 가방", ...],   // relevance 높은 순, 평균 약 70개
 "negatives": ["가맹점명: ... / 취급품목: ...", ...]}        // 같은 query pool에서 relevance 2 미만으로 판정된 문서, 경계(1) 우선, 최대 8개
```
문서 텍스트는 `t1_minimal` 템플릿(`가맹점명: … / 취급품목: …`)으로, 평가 때 문서를 인코딩하는 형식과 같습니다.

---

## [12] 4. 학습 행 만들기 `# @cell rows` — 기법 수정 지점

```python
def expand_training_rows(records, num_hard_negatives, max_positives_per_query):
    for record in records:
        positives = record["positives"][:max_positives_per_query]   # 상위 32개
        negatives = record["negatives"][:num_hard_negatives]         # 앞 3개
        if len(negatives) < num_hard_negatives: skip                 # 컬럼 수를 맞추려고 제외
        for positive in positives:
            rows.append({"anchor": query, "positive": positive, "negative_1": ..., "negative_2": ..., "negative_3": ...})
```

- query 하나가 positive 수만큼 행으로 늘어납니다(237 query → 7,270행).
- **모든 행의 컬럼 수가 같아야** sentence-transformers가 받습니다. 그래서 negative가 부족한 query는 버립니다.
- 같은 query의 행들은 같은 negative를 공유합니다.
- 반환하는 `stats`는 manifest `training_data.expansion`에 기록됩니다.

**실험 아이디어**: negative를 행마다 다르게 섞기(무작위 샘플), positive 상한을 query 크기에 따라 다르게, relevance=3인 positive만 쓰기,
query 증강(띄어쓰기·오타 변형). 바꾸면 `NOTE`에 적으세요. 테스트(`tests/test_train_eval_notebook.py`)는 이 함수가 저장소의 기준 구현과
같은지 확인하므로, 의도적으로 바꾼 뒤 노트북을 저장소에 커밋할 때는 그 테스트도 같이 고쳐야 합니다.

---

## [14] 5. 모델·loss 만들기 — 기법 수정 지점

### `resolve_query_prompt(model, preset)`
query 앞에 붙일 지시문(prompt)을 정합니다. preset에 `query_prompt` 문자열이 있으면 모델의 `prompts`에 등록해서, **학습·평가·저장된 모델·
서비스가 모두 같은 문자열**을 쓰게 합니다. 이름만 있는데 모델에 그 prompt가 없으면 에러(오타 방지). 문서에는 prompt를 붙이지 않습니다.

### `build_model(preset, hp, device)`
1. `SentenceTransformer(model_id, dtype=base_dtype)` — HF 모델 + pooling + normalize 모듈이 같이 로드됩니다.
2. `max_seq_length` 적용.
3. `lora_rank`가 있으면 peft LoRA를 **모든 linear 층**(`target_modules="all-linear"`)에 붙이고, ST 모듈 안의 모델을 LoRA 모델로 교체.
4. 학습되는 파라미터(LoRA)만 fp32로 — fp16 베이스(4B)에서 AMP가 fp16 gradient를 unscale하지 못하는 에러를 막기 위함.
5. `trainable params: … || trainable%: …` 출력(0.6B LoRA r16 ≈ 1천만 개, 약 2%).

### `build_loss(model, preset, hp, device)`

| 경우 | loss | 설명 |
|---|---|---|
| `loss="gist"` | `GISTEmbedLoss` / `CachedGISTEmbedLoss` | 대조학습(MNRL)에 **guide 모델**(학습 전 베이스 모델, fp16)을 더함. guide가 "정답보다 더 비슷하다"고 보는 in-batch negative는 오답에서 빼서, 같은 계열 query("한식"·"국밥")끼리 서로의 정답을 오답으로 배우는 문제(false negative)를 줄임 |
| `loss="mnrl"` | `MultipleNegativesRankingLoss` / `Cached…` | 표준 대조학습. query마다 자기 positive를 batch 안의 다른 모든 문서(다른 행의 positive + hard negative)보다 가깝게 |
| `mini_batch_size < batch_size` | `Cached…` 버전 | **GradCache**: batch 전체 임베딩을 grad 없이 먼저 구하고, 역전파만 mini_batch씩 나눠 계산. loss·gradient는 같고 메모리만 줄어듦(약 1.3~1.5배 느림). batch 32 × 문장 5개 = 160문장을 한 번에 역전파하면 T4가 OOM이라 기본으로 켬 |
| `target_dimension`이 있으면 | `MatryoshkaLoss`로 감쌈 | 전체 차원과 앞 1024차원 모두에서 학습 → 앞부분만 잘라 써도 성능 유지(4B) |

마지막에 `[INFO] loss: CachedGISTEmbedLoss(mini_batch_size=16)`처럼 실제로 쓴 loss를 출력합니다.

**실험 아이디어**: GIST의 `margin`·`temperature`, MNRL의 `scale`, LoRA `target_modules`(attention만), `lora_rank` 16→32/64, 다른 loss
(`CoSENTLoss` 등). 새 하이퍼파라미터를 추가하면 `HP`에 넣어야 manifest에 기록됩니다.

---

## [16] 6-a. run 관리 `# @cell runs`

| 이름 | 하는 일 |
|---|---|
| `KEEP_MARKER, PARTIAL, CKPT` | `"KEEP"` 표시 파일, `.partial`(저장 중), `.ckpt`(중간 체크포인트) 접미사 |
| `RESUME_IGNORED` | 이어서 학습할 때 처음과 달라도 되는 설정(note, keep_last_runs, save_mid_checkpoint, resume_tag, mini_batch_size) |
| `run_prefix` / `make_run_tag` | `<모델>_ft_<owner>_` + UTC `YYYYMMDD_HHMM` |
| `latest_checkpoint(root)` | `.ckpt/` 안에서 가장 큰 `checkpoint-N` |
| `prune_runs(root, prefix, keep_last)` | **내** run 중 **같은 모델**의 완성된 run을 `created_at` 최신순으로 keep_last개만 남기고 삭제. KEEP 표시, `.partial`, manifest 없는 폴더(학습 중·실패)는 건드리지 않음 |
| `notebook_code_snapshot()` | IPython `In`(이 세션에서 실행한 셀 코드 전체, 실행 순서대로)을 이어 붙임 → 모델 폴더의 `notebook_code.py`. 셀을 고쳐 가며 실험해도 이 모델을 만든 코드가 남음 |

## [17] 6-b. 학습 루프 — `train_model(preset, hp, owner, note, resume_tag, save_mid_checkpoint)`

순서대로:

1. **TAG·폴더 결정**: 새 run이면 새 TAG, `RESUME_TAG`면 그 TAG(내 모델·내 이름으로 시작하는지 확인). 최종 폴더가 이미 있으면 멈춤.
2. **run_config**: `HP` + 모델 ID + 학습 데이터 sha256.
   - 새 run + 중간 체크포인트 사용 → `.ckpt/run_config.json`에 저장.
   - 이어서 학습 → 저장된 run_config와 비교해서 다르면 멈춤(다른 설정으로 이어 붙이는 사고 방지).
3. **GPU 정리·정밀도**: `gc` + `empty_cache` + 최대 메모리 측정 초기화. compute capability 8 이상(L4·A100)이면 bf16, 아니면(T4) fp16 AMP.
4. **데이터·모델·loss**: `expand_training_rows` → `build_model` → `resolve_query_prompt` → `build_loss`.
5. **콜백**
   - `Guard`: 로그된 loss가 NaN/inf면 학습 중단 → 저장하지 않고 에러.
   - `SaveOnceAtMidpoint`: 전체 step의 절반에서 한 번 체크포인트 저장, `[체크포인트] … RESUME_TAG="…"` 출력.
6. **Trainer 서브클래스**: LoRA 체크포인트에서 이어 할 때 adapter 가중치만 읽어 넣도록 `_load_from_checkpoint`를 바꿈(기본 동작은
   merge 전 LoRA 체크포인트를 제대로 못 읽음).
7. **학습 인자**(`SentenceTransformerTrainingArguments`)

   | 인자 | 값 | 이유 |
   |---|---|---|
   | `output_dir` | `.ckpt/` 또는 `/content/ft_work/<TAG>` | 체크포인트는 Drive에, 안 쓰면 로컬 임시 |
   | `num_train_epochs`, `per_device_train_batch_size`, `learning_rate`, warmup, `weight_decay` | `HP` | |
   | `fp16` / `bf16` | GPU에 따라 | |
   | `batch_sampler=NO_DUPLICATES` | | 같은 텍스트(같은 query의 다른 행, 공유 negative)가 한 batch에 두 번 들어가 자기 자신을 오답으로 배우는 것 방지 |
   | `prompts={"anchor": query_prompt}` | | 학습 때도 query에 같은 prompt |
   | `save_strategy="no"` | | 자동 저장 끔(중간 1회만 콜백으로) |
   | `logging_steps=10`, `report_to="none"`, `seed`, `data_seed` | | |

   scheduler(`lr_scheduler_type`), `gradient_accumulation_steps` 등을 바꾸려면 여기에 인자를 추가합니다.
8. **학습** → 시간·최대 GPU 메모리 출력 → NaN이면 에러 → loss 기록 추출 → trainer·loss·guide 메모리 해제.
9. **저장 준비**
   - `extract_model_from_parallel(model, keep_fp32_wrapper=False)`: fp16/bf16 학습 때 accelerate가 모델 forward에 씌운 autocast를 벗김.
     안 벗기면 메모리 속 모델과 저장본이 다른 정밀도로 계산돼 검증이 엉뚱하게 실패합니다.
   - LoRA면 `merge_and_unload()`로 LoRA를 베이스 가중치에 합쳐 **보통 모델 하나**로 만듦 → 서비스는 peft 없이 불러올 수 있음.
10. **`save_verified`**(아래) → `.partial/`에 저장·검증.
11. **기록 파일**
    - `eval_config.yaml`: 이 모델을 평가할 때 쓸 설정(prompt 이름, normalize, 차원, dtype). 로컬로 가져오면 `configs/models/<TAG>.yaml`이 됨.
    - `notebook_code.py`: 코드 사본.
    - `model_manifest.json`: 아래 표.
12. `.partial` → `<TAG>`로 이름 변경(이름이 바뀐 폴더만 "완성된 모델"), `.ckpt/` 삭제, 오래된 run 정리, `final_dir` 반환.

`model_manifest.json` 주요 키:

| 키 | 내용 |
|---|---|
| `tag`, `owner`, `base_model_id`, `base_model_config`, `framework`, `precision` | 무엇을 누가 어떻게 |
| `hyperparameters` | `HP` 전부 + note·resume_tag |
| `training_data` | 학습 데이터 경로·sha256·펼친 행 통계·meta(qrels 종류·template·데이터 만든 커밋) |
| `data_version` | `data_version.json` 전체(데이터 git 커밋, 파일별 sha256) |
| `code` | `notebook_code.py`와 그 sha256 |
| `training_result` | 학습 시간, step 수, 최대 GPU 메모리, 중간 체크포인트 step, 이어 학습 여부, loss 기록 |
| `serving` | **서비스가 따라야 할 값**: 문서 template, query prompt, 임베딩 차원, normalize, cosine, max_seq_length, 저장 dtype |
| `environment` | 라이브러리 버전, GPU |
| `evaluations` | 평가할 때마다 추가(split, 지표, 기준 모델) |

### `save_verified(model, saved_dir, prompt_name, device, save_dtype)`

1. 저장 전 모델로 검증 문장 5개(`VERIFY_TEXTS`: query 3개는 prompt 포함, 문서 2개)를 인코딩 → 기준값.
2. 모델을 CPU로(4B에서 재로드할 GPU 메모리 확보).
3. `save_dtype`(float16)으로 저장 → **새로 불러와서** 같은 문장 인코딩 → 최소 cosine ≥ 0.999면 통과 `[검증] 저장본(float16) … 일치 확인`.
4. 안 맞으면 `[경고]` 후 float32로 다시 저장·검증(fp32로 학습한 모델은 미리 복사해 둔 학습 가중치 그대로 저장 — fp16으로 깎인 값이 아님).
   그래도 안 맞으면 에러(폴더는 `.partial`로 남고 쓰지 않음).

이 검증이 잡는 사고: pooling·normalize·prompt 설정이 빠진 채 저장, LoRA merge 실패, fp16 저장 시 값 넘침(NaN은 불일치로 판정).

---

## [19] 7. 평가 `# @cell eval` — 고치지 말 것

로컬 공식 evaluator(`scripts/13_evaluate_run.py` → `store_search_ai.evaluation.evaluator`)와 **같은 계산**입니다.
`tests/test_train_eval_notebook.py`가 이 셀을 실제로 실행해 공식 evaluator와 지표·신뢰구간·비교 결과가 같은지 확인하고,
결과를 로컬로 가져올 때 `import_colab_results.py --verify`가 다시 채점해 확인합니다.

| 이름 | 하는 일 |
|---|---|
| `ast.Num` 보정 | ir_measures 0.4.3이 Python 3.12+에서 사라진 `ast.Num`을 써서 나는 에러를 그 함수 하나만 대체 |
| `METRIC_SPECS` | 지표 정의. relevance 2 이상을 정답으로 보는 지표는 `rel=2`. **nDCG@10**(주 지표, 등급 반영), P@10, MRR@100, Recall@50/100, Bpref, Judged@10/100 |
| `TEMPLATE_COLUMNS` | 문서 템플릿 → corpus 컬럼(`t1_minimal` 기본) |
| `load_qrels`, `load_run_csv` | TREC qrels / run.csv 읽기 |
| `calculate_metrics` | ir_measures로 전체 평균 + 쿼리별 지표 |
| `bootstrap_ci` | 쿼리를 복원추출 10,000번 → 평균의 95% 신뢰구간 |
| `paired_permutation_pvalue` | 같은 쿼리에서 두 모델 점수 차이의 부호를 무작위로 뒤집어 "우연히 이만큼 차이 날 확률" |
| `compare_runs` | 기준 모델 대비 Δ 평균·Δ 신뢰구간·p-value·wins/ties/losses |
| `validate_run` | 누락·모르는 query, 중복 (query, doc), 잘못된 rank 수 |
| `score_run` | 위를 모아 report(dict) 생성 — 공식 evaluator와 같은 형식 |
| `exact_search` | query·문서 임베딩 내적(정규화됐으므로 cosine) → query마다 top 100. 근사 검색(ANN)이 아닌 정확한 검색 |
| `load_encoder(cfg)` | 평가할 모델 로드. dtype은 `torch_dtype`(4B는 float16), 없으면 **float32로 고정** — 지정하지 않으면 transformers 5가 모델마다 다른 dtype(Qwen3=bf16, fp16 저장본=fp16)으로 올려 기준·학습 모델 점수에 정밀도 차이가 섞임 |
| `encode(model, texts, cfg, is_query)` | query면 prompt 적용 → 인코딩 → `target_dimension`만큼 자름 → 정규화. **자른 뒤 정규화**해야 cosine이 맞음 |
| `evaluate(cfg, split, …)` | 아래 |
| `format_report` | 출력용 문자열 |
| `leaderboard(split, include_unofficial)` | `EVAL_DIR`의 평가 json을 전부 모아 nDCG@10 순. 비공식(SMOKE)은 기본 제외. `libs` = ST/transformers 버전 |
| `release_gpu()` | `gc` + `empty_cache`. 부르기 전에 호출한 쪽에서 모델 변수를 `None`으로 지워야 실제로 풀림 |

`evaluate`의 순서:
1. split이 test인데 `allow_test=False`면 에러(test 보호).
2. 모델 로드(이미 로드된 `model`을 넘기면 재사용).
3. corpus 전체 인코딩(넘겨받은 `doc_embeddings`가 있으면 재사용 — prompt만 다른 변형 비교 때 시간 절약).
4. 해당 split query 인코딩 → `exact_search` → `runs/model_eval/<이름>/run_<template>_<split>.csv` 저장.
5. 기준 모델 run이 있으면 비교 포함해 채점 → `runs/evaluation/`에 json·per_query csv 저장.
   json에는 `official`, `corpus_docs`, `model_id`, `evaluated_at`, `library_versions`, `evaluated_with`가 추가됩니다.
6. 평가한 모델 폴더에 `model_manifest.json`이 있으면(fine-tuned 모델) `evaluations`에 결과 추가.

---

## [21] 8. 학습

```python
final_dir = None
if not EVAL_RUN_TAG:
    final_dir = train_model(preset, HP, OWNER, NOTE, resume_tag=RESUME_TAG, save_mid_checkpoint=SAVE_MID_CHECKPOINT)
```
로그에서 볼 것: `[INFO] 학습 데이터: {... 'n_rows': 7270}`(팀원과 같아야 같은 데이터), `[INFO] query prompt`, `[INFO] loss`,
`[체크포인트]`, `[INFO] 학습 시간 … GPU 최대 사용 …`, `[검증] … 일치 확인`, `[완료] 최종 모델: …`.

## [23] 9. 평가 (val)

1. `base_cfg` = 지금 preset에서 `train`을 뺀 것 = **같은 모델의 zero-shot**. 그 run.csv가 없으면 먼저 평가(처음 한 번, 문서 21만 개 인코딩).
2. `final_dir`이 `None`이면(학습 셀이 중단·실패) 안내하고 멈춤. 8번이 시작할 때 `final_dir = None`으로 비우므로, 같은 세션에서
   앞서 끝난 run이 있어도 그 모델을 새 모델로 잘못 평가하지 않습니다.
3. 평가 대상 = `EVAL_RUN_TAG`가 있으면 그 run, 없으면 방금 학습한 `final_dir`. 그 폴더의 `eval_config.yaml`로 설정.
4. 기준 모델 대비로 채점·출력 → 모델 변수 비우고 GPU 해제.

## [25] 10. 리더보드

`leaderboard("val")` 결과에서 주요 열만 출력. Δ·p는 기준 모델과의 비교값이라 **기준 모델 행 자신은 `-`**.

## [27] 11. zero-shot 비교표

`ZERO_SHOT_MODELS`에 preset 키를 적으면 차례로 평가합니다. 이미 평가된 모델은 건너뜁니다. 같은 모델 ID·dtype·차원이면(prompt만 다른
변형) 문서 임베딩을 재사용해 빠릅니다. `BASELINE_FOR_TABLE`을 주면 각 모델의 Δ·p도 계산합니다.

## [29] 12. SMOKE 확인

`SMOKE=True`일 때만 동작. 모델 폴더 구성, LoRA merge, 임시 폴더 정리, 중간 체크포인트, loss 유한, manifest 평가 기록, val 쿼리 누락·중복 0,
비교 계산, 리더보드, 비공식 분리, test 차단을 `[OK]/[FAIL]`로 점검하고 전부 OK면 `통과`.

## [31] 13. KEEP

`(FINETUNE_DIR / "TAG" / "KEEP").touch()` — 빈 파일 하나로 `prune_runs` 자동 삭제에서 제외됩니다.

## [33] 14. test 평가

`FINAL_TEST=True`일 때만. 기준 zero-shot의 test run이 없으면 먼저 만들고, 9번에서 정한 `eval_cfg` 모델을 test로 채점해 비교합니다.
팀이 최종 후보를 정한 뒤 **한 번만** 실행합니다(여러 번 보고 고르면 test가 val처럼 오염됨).

---

## 자주 묻는 코드 질문

**Q. 셀을 고쳤는데 반영이 안 돼요.** 함수 정의 셀은 고친 뒤 **그 셀을 다시 실행**해야 새 함수가 등록됩니다. 그다음 8번부터.

**Q. `notebook_code.py`에 같은 함수가 여러 번 들어 있어요.** 세션에서 실행한 순서대로 전부 남기기 때문입니다. **마지막에 나온 정의**가
실제로 쓰인 코드입니다.

**Q. 왜 `src/`를 import하지 않나요?** Colab에 프로젝트 전체를 올리고 동기화하는 번거로움을 없애고, 셀에서 바로 기법을 고칠 수 있게
하려고 노트북이 필요한 코드를 직접 담았습니다. 대신 채점과 행 펼치기는 테스트로 저장소의 공식 구현과 같은지 확인합니다.

**Q. 서비스에서는 무엇을 쓰나요?** `runs/finetune/<TAG>/` 폴더를 `SentenceTransformer(폴더)`로 불러오고, query 인코딩 때 manifest
`serving.query_prompt`를 붙이고, 문서는 `serving.document_template` 형식으로 만들고, `embedding_dim`만큼 잘라 정규화하면 평가와 같은
결과가 나옵니다.
