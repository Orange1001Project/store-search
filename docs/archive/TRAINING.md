# 임베딩 학습·평가 참고서 (종료된 단계, 다시 돌릴 때용)

임베딩 학습 단계는 끝났습니다. **임베딩 v1 = bge-m3 mj(`bge_m3_ft_mj_20261014_0743`, 2026-10-16 선택)**.
이 문서는 나중에 (a) 학습·평가 코드 구조를 이해하거나 (b) 학습·평가를 다시 돌릴 때 보는 참고서입니다.
예전 `TRAINING_TEAM.md`·`TRAIN_EVAL_NOTEBOOK.md`·`MODELING.md`·`EMBEDDING_V1_PLAN.md`를 합쳤습니다.
명령·경로·플래그는 2026-11-10 기준 코드(`scripts/*.py` argparse, `colab/train_eval.ipynb`)와 맞춰 두었습니다.

## 0. 한눈에 — 무엇이 어디 있나

| 무엇 | 어디 |
|---|---|
| 학습 + val 채점 (Colab, 실제로 쓴 방식) | `colab/train_eval.ipynb` 한 파일 (`src/`를 import하지 않음) |
| 학습 데이터 만들기 | `scripts/prepare_finetune_dataset.py` → `data/finetune/train_pairs.jsonl` + `train_pairs.meta.json` |
| Drive에 올릴 데이터 묶기 | `scripts/pack_for_colab.py` → `colab_upload/data/` |
| Colab 결과 가져오기 | `scripts/import_colab_results.py` |
| 로컬 GPU로 평가 | `scripts/14_run_model_eval.py` → `scripts/15_score_model_runs.py` |
| 공식 채점(단일 기준) | `scripts/13_evaluate_run.py` → `store_search_ai.evaluation.evaluator` |
| qrels 바뀐 뒤 재채점 | `scripts/rescore_evaluations.py` (Drive 쪽은 노트북 16번) |
| 모델 설정 | `configs/models/*.yaml` (zero-shot은 HF ID, fine-tuned는 `models/<TAG>` 경로) |
| 실험 기록표 | `results/experiments.csv` (평가 하나당 한 줄, 자동) |
| run별 기록(manifest·eval_config·notebook_code) | `results/finetune_runs/<TAG>/` (git) |
| 모델 가중치 | `models/<TAG>/` (.gitignore — git에 없음) |
| v1 후보 비교표 | `results/model_comparison/final_v1_val/` (`summary.csv`, `pairs.csv`, `README.md`) |
| 노트북 ↔ 공식 구현 일치 테스트 | `tests/test_train_eval_notebook.py` |

## 1. 코드 구성

### 1-1. 평가 구조 (BEIR 3단 분리)

```
텍스트 → [Encoder]      텍스트 → 벡터만 안다          src/store_search_ai/models/
       → [ExactSearch]  벡터 → top-k run만 안다      src/store_search_ai/retrieval/exact_search.py
       → [Evaluator]    run 채점만 안다(단일 기준)    scripts/13_evaluate_run.py → evaluation/evaluator.py
```

- zero-shot과 fine-tuned를 구분하지 않습니다. `configs/models/*.yaml`의 `model_id`가 HF ID든 로컬 경로든 `SentenceTransformerEncoder`가 똑같이 로드합니다.
- metric 계산은 evaluator 한 곳에만 둡니다. 14·15번은 13번을 **서브프로세스로** 호출합니다(evaluator를 직접 import하지 않음 — 같은 채점을 CLI 계약으로 강제).
- 예외는 Colab 노트북 `7. 평가` 셀뿐입니다. 혼자 돌도록 채점 코드를 **복제**했고, 테스트와 `import_colab_results.py --verify`가 공식 evaluator와 같은지 확인합니다.
- ANN(Qdrant/FAISS)으로 바꿀 때는 `ExactCosineSearch`의 생성자·`search()` 시그니처만 유지하면 됩니다.

| 모듈 | 역할 |
|---|---|
| `models/base.py` | `BaseEncoder` 인터페이스(`encode_corpus`, `encode_queries`, `name`) |
| `models/sentence_transformer_encoder.py` | `configs/models/*.yaml` 하나로 sentence-transformers 모델 로드. dtype: yaml `torch_dtype` → 없으면 GPU float16 / CPU float32 |
| `models/random_encoder.py` | 네트워크·GPU 없이 배관만 검증하는 가짜 인코더(`--dummy`) |
| `models/model_eval.py` | 14번의 오케스트레이션 조각(인코더 선택, 13번 호출 명령, manifest 엔트리) |
| `models/leaderboard.py` | 15번의 run 탐색·리더보드 정렬 |
| `retrieval/exact_search.py` | `ExactCosineSearch` — 전체 코퍼스와 정확한 cosine top-k |
| `evaluation/evaluator.py` | 채점 본체: qrels/run 로딩, `ir_measures` 계산, bootstrap CI, paired permutation, `build_evaluation_report` |
| `evaluation/model_evaluation.py` | 인코딩 → 검색 → 공식 채점 → 저장 → manifest 기록 한 번에(가져오기·테스트용, 노트북과 같은 형식) |
| `common/hf_compat.py` | transformers 4/5·sentence-transformers 3~5 API 차이 흡수(노트북 `2. 호환` 셀과 같은 함수) |

### 1-2. 학습 코드

| 모듈 | 역할 |
|---|---|
| `data/finetune_dataset.py` | qrels → 학습 쌍(`build_training_pairs`). positive/negative 후보 자체를 바꾸려면 여기 |
| `training/finetune.py` | `expand_training_rows`(학습 행 펼치기 기준 구현), run TAG, 체크포인트, `prune_finetune_runs` |
| `training/st_finetune.py` | `run_finetune(FinetuneConfig)` — 노트북과 같은 학습 방식의 **로컬 GPU용 참조 구현**(코드 사본은 `code_snapshot.zip`) |
| `colab/train_eval.ipynb` | 실제 학습 경로. 모델별 차이는 `MODEL_PRESETS`뿐이고 학습 루프는 같음 |

학습 데이터 형식과 펼치기:
- jsonl 한 줄: `{"query_id", "query", "positives": [...], "negatives": [...]}`. 문서 텍스트는 `t1_minimal`(`가맹점명: … / 취급품목: …`).
- positives: pool에서 relevance ≥ 2인 문서 전부(높은 순). negatives: 같은 pool의 relevance < 2(경계 1 우선, 최대 `--max-negatives`=8).
- 같은 텍스트 문서는 한 번만, positive와 같은 텍스트는 negative에서 뺌. positive가 없는 query는 제외.
- 펼치기: (query, positive)마다 한 행, query당 positive 최대 `max_positives_per_query`(32). 모든 행의 negative 수가 `num_hard_negatives`로 같아야 해서 부족한 query는 빠짐.
- 현재 데이터(sha `ec3a9b61`): 학습 query 215개, hard negative 3이면 6,650행.

학습 방식 요약:
- Arctic·BGE-M3: full fine-tuning, lr 2e-5. Qwen3: LoRA(r=16, all-linear) → 저장 전 `merge_and_unload()`로 보통 모델 하나로.
- loss 기본 `gist`(GISTEmbedLoss, 학습 전 베이스가 guide — 같은 계열 query끼리의 false negative 완화). 대안 `mnrl`.
  `mini_batch_size < batch_size`면 Cached 버전(GradCache): **결과는 같고 메모리만 줄어듦**. `target_dimension`이 있으면 Matryoshka로 감쌈(4B).
- batch sampler `NO_DUPLICATES`, query prompt는 학습 때도 preset 값 그대로(`prompts={"anchor": …}`). 문서에는 prompt 없음.

## 2. 실행 순서

### 2-1. 학습 데이터 (로컬, GPU 불필요) — train qrels가 바뀔 때만

```bash
python scripts/prepare_finetune_dataset.py
```
- 입력: `--qrels` 기본값은 `benchmark/storesearch_ko_v1/qrels_train.csv`(최종), 없으면 `--round` 라운드의 provisional. 그 외 `--template`(기본 `t1_minimal`), `--max-negatives`(기본 8), `--output`.
- jsonl과 meta.json은 **같이** 커밋합니다(노트북이 sha를 대조).

### 2-2. Colab 학습·평가

1. 데이터 묶기 → Drive 업로드(데이터가 바뀔 때만):
   ```bash
   python scripts/pack_for_colab.py        # 옵션: --config, --output(기본 colab_upload)
   ```
   `colab_upload/data/`(train_pairs.jsonl·meta, corpus parquet, queries.csv, qrels_val/test.trec, `data_version.json`)를
   Drive `내 드라이브/store-search-ai/data/`로 **폴더째** 올립니다(기존 data는 지우고). 일부 파일만 올리면 노트북 3번이 sha 불일치로 멈춥니다.
2. Colab **파일 > 노트북 업로드** → `colab/train_eval.ipynb`. 런타임 GPU 확인.
3. `1. 설정`에서 `OWNER`(영문 소문자 시작 2~16자) 입력. 처음엔 `SMOKE = True`로 **모두 실행** → 맨 아래 `통과` 확인(결과는 `runs_smoke/`).
4. `SMOKE = False` → 실행 흐름:
   ```
   GPU 확인 → 설치 → Drive 연결 → 1. 설정 → 2. 호환 → 환경 점검 → 3. 데이터 → 4·5·6·7(함수 정의)
   → 8. 학습 → 9. 평가(val, 처음엔 기준 zero-shot도) → 10. 리더보드 → (남길 run) 13. KEEP
   ```
5. 고친 뒤 다시 실행할 셀(세션 유지 시):

| 바꾼 것 | 다시 실행 |
|---|---|
| `HP`·`NOTE`·`MODEL` | 1 → 8 → 9 → 10 |
| `SMOKE` | 1 → **3** → 8 → 9 → 10 (3번 빼면 "3. 데이터 셀을 다시 실행하세요"로 멈춤) |
| 4·5·6번 셀 | 고친 셀 → 8 → 9 → 10 |
| 학습 없이 기존 run 평가 | 1(`EVAL_RUN_TAG`) → 9 → 10 (함수 정의 셀 2~7이 먼저 실행돼 있어야 함) |
| Drive `data/` 교체 | 1 → 3 → 8 → 9 → 10 (기준도 다시 재려면 `runs/model_eval/<기준이름>/` 삭제) |
| 8번 OOM·에러 | 런타임 > 세션 다시 시작 → 위에서부터 |

6. 끊겼을 때(Drive `runs/finetune/`로 판단):

| 보이는 것 | 조치 |
|---|---|
| `<TAG>.ckpt`(안에 `checkpoint-N` 없음) | `.ckpt` 삭제 → 처음부터 |
| `<TAG>.ckpt/checkpoint-N/` | `RESUME_TAG = "<TAG>"`, **나머지 설정은 처음과 똑같이** → 모두 실행 |
| `<TAG>.partial` + `.ckpt` | 위와 같음(`.partial` 자동 삭제) |
| `<TAG>`(manifest 있음) | `EVAL_RUN_TAG = "<TAG>"` → 모두 실행(8번 자동 건너뜀) |

   - 이어 하기 때 달라도 되는 값: `note`, `keep_last_runs`, `save_mid_checkpoint`, `resume_tag`, `mini_batch_size`(노트북 `RESUME_IGNORED`). 그 외·학습 데이터·precision이 다르면 거부.
   - 이어 하기는 같은 종류 GPU에서만(T4끼리, L4·A100끼리).

### 2-3. 결과 가져오기 (로컬)

```bash
# Drive의 store-search-ai 폴더 내려받아 압축 해제(runs/만 있으면 됨)
python scripts/import_colab_results.py --drive-dir "<내려받은 store-search-ai>" --dry-run   # 무엇을 옮길지만
python scripts/import_colab_results.py --drive-dir "<내려받은 store-search-ai>" --verify
python scripts/import_colab_results.py --drive-dir ... --models <TAG> [<TAG> ...]           # KEEP 외에 모델도 복사
git add results/ artifacts/ configs/models/   # 커밋
```

| Drive `runs/` | → 저장소 | git |
|---|---|---|
| `model_eval/<이름>/run_<template>_<split>.csv` | `results/model_eval/<이름>/` | 커밋 |
| `evaluation/*_evaluation.json`, `*_per_query.csv` (공식만) | `artifacts/evaluation/storesearch_ko_v1/` | 커밋 |
| `finetune/<TAG>/`의 manifest·eval_config·notebook_code (모든 run) | `results/finetune_runs/<TAG>/` | 커밋 |
| (자동) 평가마다 한 줄 | `results/experiments.csv` | 커밋 |
| `finetune/<TAG>/` 모델 전체 — KEEP + `--models` | `models/<TAG>/` | 안 함 |
| 그 run의 `eval_config.yaml` | `configs/models/<TAG>.yaml` | 커밋 |

- `results/` 밑에 손으로 복사하지 않습니다. 정식 이름이 아닌 run 파일(`run_..._pre.csv` 등)은 `[건너뜀]`.
- `--verify`: 로컬 공식 evaluator로 다시 채점해 Colab 점수와 비교, 다르면 종료코드 1.
- `--verify`와 무관하게, 저장소 qrels로 채점한 값과 다른(예전 qrels) 평가는 json·기록표 줄을 가져오지 않습니다 → Drive에서 노트북 16번 재채점 후 다시 가져오기.
- Drive zip에서 빈 `KEEP` 파일이 빠질 수 있음 → `--models <TAG>`.

### 2-4. 로컬 GPU로 평가 (선택)

```bash
pip install -e ".[embedding]"     # 로컬 학습(run_finetune)까지면 ".[train]"
python scripts/14_run_model_eval.py --dummy --split val                                    # 배관만 검증
python scripts/14_run_model_eval.py --model-config configs/models/bge_m3_ft_mj_20261014_0743.yaml --split val
python scripts/15_score_model_runs.py --split val                                         # results/model_eval/ 전체 → leaderboard_val.csv
```
- 14번 옵션: `--template`(기본 `t1_minimal`), `--top-k`(100), `--tag`, `--output-dir`(`results/model_eval`), `--skip-evaluate`.
- 결과: `results/model_eval/<모델명>/run_<template>_<split>.csv` + 13번 채점.
- 13번 단독: `python scripts/13_evaluate_run.py --run <run.csv> --tag <이름> [--qrels ...] [--compare-run <기준 run> --compare-tag <이름>]` (Makefile `make evaluate RUN=... TAG=...`).

### 2-5. qrels가 바뀌었을 때 (보충 판정 라운드 뒤)

```bash
python scripts/11_build_qrels.py
python scripts/12_validate_benchmark.py --stage final
python scripts/rescore_evaluations.py --dry-run      # 무엇을 다시 채점할지
python scripts/rescore_evaluations.py                # test는 --include-test 줄 때만
python scripts/pack_for_colab.py                     # Drive data/ 교체 → 노트북 16번(Drive 평가 재채점)
```
- `rescore_evaluations.py`: 같은 run 파일을 새 qrels로 다시 채점해 json·per_query·`experiments.csv` 지표를 갱신(모델 재실행 없음). 비활성 쿼리 행은 run에서 지우고 채점.
- 판정용 val+test 검색 결과(채점 없음)는 노트북 15번 → `scripts/16_supplemental_round.py make-runs --round <라운드> --runs-dir <pooling_runs>`.

## 3. Colab 노트북 셀 (`colab/train_eval.ipynb`)

> **셀 첫 줄 `# @cell <이름>`은 지우지 마세요.** `tests/test_train_eval_notebook.py`가 이 이름으로 셀을 찾아 실제로 실행합니다
> (테스트가 쓰는 이름: `compat`, `rows`, `runs`, `eval`, `board`, `pool`, `rescore`. `settings`에도 표시가 있음).
> 테스트는 `7. 평가`가 공식 evaluator와, `4. 학습 행`이 `training.finetune.expand_training_rows`와 같은지 확인합니다 — 의도적으로 바꾸면 테스트도 같이 고칩니다.

| 셀(제목) | `@cell` | 하는 일 | 고치나 |
|---|---|---|---|
| GPU 확인 / 설치 / Drive 연결 | – | torchao 제거, `PYTORCH_CUDA_ALLOC_CONF`, `ir-measures==0.4.3`·`pytrec-eval-terrier==0.5.10`만 설치, `/content/drive` 마운트 | 아니오 |
| 1. 설정 | settings | `OWNER`·`MODEL`·`NOTE`·`SMOKE`·`RESUME_TAG`·`SAVE_MID_CHECKPOINT`·`EVAL_RUN_TAG`·`FINAL_TEST`·`EVAL_DTYPE`·`EVAL_BATCH_SIZE`, `MODEL_PRESETS`, `HP`, 경로 | **예** |
| 2. 라이브러리 버전 호환 (+ 환경 점검) | compat | `training_precision()`, `dtype_kwargs`, `warmup_kwargs` 등, `check_environment()` | 거의 안 함 |
| 3. 데이터 불러오기 | – | `data_version.json` sha 대조, corpus·active queries·qrels·학습 데이터 로드, `DATA_SMOKE` 기록 | 아니오 |
| 4. 학습 행 만들기 | rows | `expand_training_rows`, 오타 증강 `augment_typo_records`(기본 꺼짐) | 기법 실험 |
| 5. 모델·loss | – | `resolve_query_prompt`, `build_model`(LoRA), `build_loss`(GIST/MNRL, Cached, Matryoshka) | 기법 실험 |
| 6. 학습 루프·저장·기록 | runs (+ 다음 셀) | run 관리(TAG, `prune_runs`, `notebook_code_snapshot`) / `train_model`, `save_verified` | Trainer 인자만 |
| 7. 평가 | eval | 인코딩·exact 검색·채점·리더보드 — 공식 evaluator 복제 | **절대 안 함** |
| 8. 학습 | – | `train_model(...)` (`EVAL_RUN_TAG`면 건너뜀) | 아니오 |
| 9. 평가 (val) | – | 같은 모델 zero-shot(없으면 먼저) + 학습 모델 채점, Δ·p | 아니오 |
| 10. 리더보드 | board | nDCG@10 순 + 서비스 지표(nDCG@10 판정만, bad@3, top1_ok, 유형별 bad@3) | 아니오 |
| 11. zero-shot 비교표 | – | `ZERO_SHOT_MODELS`, `BASELINE_FOR_TABLE` | 목록만 |
| 12. SMOKE 확인 | – | `[OK]/[FAIL]` 점검 → `통과` | 아니오 |
| 13. KEEP | – | `(FINETUNE_DIR / "<TAG>" / "KEEP").touch()` | TAG만 |
| 14. test 평가 | – | `FINAL_TEST=True`일 때만 | 최종 1회만 |
| 15. 판정용 검색 결과 | pool | `POOL_RUN_MODELS`·`POOL_RUN_FINETUNED` → `runs/pooling_runs/<이름>.csv`(top `POOL_DEPTH`=100, 채점 없음) | 목록만 |
| 16. 기존 평가 다시 채점 | rescore | qrels 교체 후 Drive 평가 재채점(`rescore_evaluations.py`와 같은 규칙) | 아니오 |

- 함수 정의 셀(2·4·5·6·7)은 전역 값(`RUN_DIR`, `corpus`, `RECORDS` …)을 **호출 시점에** 읽습니다. 설정·데이터만 바꿨으면 정의 셀은 다시 안 돌려도 됩니다.
- 정본은 저장소 `colab/train_eval.ipynb`입니다. Colab에서 고쳤으면 **파일 > 다운로드 > .ipynb**로 받아 덮어쓰기. 다시 올릴 때는 Drive `Colab Notebooks/`의 옛 사본을 먼저 지웁니다.
- `notebook_code.py`에 같은 함수가 여러 번 있으면 **마지막 정의**가 실제로 쓰인 코드입니다.

`HP` 기본값(팀 공통, manifest에 그대로 기록):

| 키 | 기본 | 비고 |
|---|---|---|
| `num_epochs` / `warmup_ratio` / `weight_decay` / `max_seq_length` | 2 / 0.1 / 0.01 / 128 | 문서 평균 24자 |
| `batch_size` / `mini_batch_size` | preset (Arctic·BGE·0.6B 32/16, 4B 8/4) | batch는 결과에 영향, mini_batch는 메모리만 |
| `learning_rate` | preset (Arctic·BGE 2e-5, Qwen3 1e-4) | |
| `num_hard_negatives` | 3 (Qwen3 0.6B preset 6) | 7 이상이면 negative 부족 query가 빠짐 |
| `max_positives_per_query` | 32 | |
| `typo_variants_per_query` / `typo_positives_per_variant` | 0 / 8 | 오타 증강은 효과 없음(Δ +0.001, p=0.70) → 0 |
| `loss` | preset (`gist`, 4B `mnrl`) | |
| `lora_rank` / `lora_alpha` / `lora_dropout` | preset(None=full FT, Qwen3 16) / 32 / 0.05 | |
| `base_dtype` / `save_dtype` | preset(4B float16, 나머지 float32) / float16 | |
| `seed` / `keep_last_runs` | 20260831 / 3 | |

T4(15GB) 기준: Arctic·BGE·Qwen3 0.6B는 기본값. OOM이면 `mini_batch_size` 절반(결과 같음, NOTE 불필요) → 그래도 안 되면 `batch_size` 16 또는 `loss="mnrl"`(NOTE에 기록).
Qwen3 4B는 preset(fp16 베이스, batch 8, mnrl)로 빠듯하고 NaN이면 L4/A100. 8B는 T4 불가.

## 4. 기록 규칙

| 어디 | 누가 | 무엇 |
|---|---|---|
| `model_manifest.json` (run 폴더) | 자동 | 설정·데이터·코드·환경·서빙 값·평가 기록 — **손대지 않음** |
| 설정 셀 `NOTE` | 사람 | 기본값에서 바꾼 것 한 줄. 모델 밖 처리(쿼리 전처리 등)를 넣었으면 `서비스도 필요:`로 시작 |
| `results/experiments.csv` | 자동(가져올 때) | 평가 하나당 한 줄 |

`model_manifest.json` 주요 키: `tag`·`owner`·`base_model_id`·`precision` / `hyperparameters`(HP 전체 + note·resume_tag) /
`training_data`(jsonl sha256, 펼친 행 통계, prepare_meta) / `data_version`(pack 때의 git 커밋·파일 sha) / `code`(`notebook_code.py`와 해시) /
`training_result`(시간·step·GPU 메모리·loss·`resumed_from`) / **`serving`**(document template, query prompt 이름·원문, 차원, normalize, cosine, max_seq_length, `saved_dtype`) /
`environment`(라이브러리·GPU) / `evaluations`(학습 직후 점수 — 재채점 후 현재 점수는 평가 json을 봄).
서빙은 `serving`을 그대로 따릅니다: `SentenceTransformer(모델폴더)` + query에 `serving.query_prompt` + 문서는 `document_template` + 차원만큼 자른 뒤 정규화.

`results/experiments.csv` 열: `eval_tag, model, kind, owner, base_model, note, train_data_sha8, gpu, precision, eval_dtype, libs,
nDCG@10, Judged@10, Recall@100, MRR@100, Bpref, delta_nDCG@10, p_nDCG@10, baseline, keep, evaluated_at`.
같은 `eval_tag`는 새 값으로 바뀌고, Drive에서 지워진 run의 예전 줄은 남습니다.

Drive run 폴더 규칙(`runs/finetune/<TAG>/`, TAG = `<모델이름>_ft_<OWNER>_<UTC YYYYMMDD_HHMM>`):
- 저장은 `<TAG>.partial/`에 먼저 → 다시 로드해 임베딩 비교(cosine ≥ 0.999) → manifest → `<TAG>`로 이름 변경. `.partial`이 남아 있으면 끊긴 것.
- 학습 절반 지점에서 `<TAG>.ckpt/checkpoint-N/` 1회 저장(full FT는 약 7GB). 최종 저장 성공 시 자동 삭제. 공간이 없으면 `SAVE_MID_CHECKPOINT = False`.
- 저장 후 **같은 OWNER·같은 모델의 완성된 run은 최신 `keep_last_runs`(3)개만** 남기고 지웁니다. KEEP·`.partial`·`.ckpt`·남의 run은 안 건드림.
- **`KEEP`** = run 폴더 안의 빈 파일(노트북 13번으로 생성). 자동 정리에서 빠지고, 가져올 때 모델 가중치가 `models/<TAG>/`로 복사되며 기록표 `keep=True`.
  **Drive를 내려받기 전에** 붙입니다. 대상: 모델별 baseline, 서비스 후보, 발표·비교에 계속 쓸 run.
- KEEP한 run은 `results/finetune_runs/<TAG>/`에 학습 때 쓴 노트북 사본과 짧은 README를 같이 두면 재현이 쉽습니다(예: `qwen3_embedding_0_6b_ft_kse1_20261006_0708/`).

## 5. 바꾸지 않는 것 · 주의

**바꾸지 않는 것**
- 노트북 `7. 평가` 셀(채점 로직)과 정답 파일(qrels·queries·corpus). 채점을 바꿔야 하면 공식 evaluator부터 바꾸고 노트북 셀도 같이, 모든 run 재채점.
- 채점 라이브러리 버전(`ir-measures==0.4.3`, `pytrec-eval-terrier==0.5.10`).
- **test split은 보지 않습니다.** 선택은 val로, test는 최종 후보 1개만 `FINAL_TEST = True`로 1회. test를 보고 다시 고르지 않습니다.
- 셀 첫 줄 `# @cell <이름>`.

**비교 규칙** — 다음이 모두 같은 결과끼리만 비교합니다:
학습 데이터 해시(`train_data_sha8`) · 학습 precision(T4=fp16, L4/A100=bf16) · `eval_dtype` · `libs`(ST/transformers 버전) · val 쿼리 수(현재 124).
`eval_dtype`이 비어 있으면 2026-10-07 이전 결과 → 다시 평가. 리더보드 `query_count`가 124가 아니면 qrels 변경 전 점수 → 16번 재채점.

**숫자 읽는 법**
- val 124개라 nDCG@10 95% CI는 ±0.025 정도, 같은 설정 재실행도 ±0.005 흔들림. **Δ ≥ 0.03이고 p < 0.05일 때만 "개선"**.
- Judged@10 < 0.9이면 점수가 실제보다 낮게 나옴. 0.95 미만인 새 계열 모델은 리더보드 `nDCG@10(판정만)`으로 보고, 사람 판정은 후보를 모아 한 번에.
- 서비스 지표 `bad@3`(상위 3개에 오답이 섞인 쿼리 비율, 목표 ≤ 0.05).
- 오타 쿼리는 2026-10-14부터 비활성(val 136 → 124, `configs/benchmark/inactive_queries_v1.yaml`). 그 전 점수와 직접 비교하지 않습니다.

**정밀도(fp32·fp16·bf16) 핵심**
- fp16은 최댓값 65,504라 넘치면 inf/NaN, bf16은 범위가 fp32와 같고 자릿수가 적음. 학습은 AMP(가중치 fp32, 연산만 반 정밀도).
- 학습 정밀도는 GPU 세대로 정함: compute capability ≥ 8(L4·A100) bf16, T4 fp16, CPU fp32(노트북 `training_precision()`, 로컬 `st_finetune._pick_precision`).
  `torch.cuda.is_bf16_supported()`는 에뮬레이션까지 True라 **T4에서도 True** → 쓰지 않습니다.
- LoRA 파라미터는 항상 fp32(fp16이면 GradScaler unscale 에러). GIST guide는 학습 정밀도 계열의 반 정밀도.
- 저장은 float16 → 재로드 임베딩이 cosine ≥ 0.999로 안 맞으면 float32로 다시 저장(manifest `serving.saved_dtype`).
  비교 전에 `extract_model_from_parallel(model, keep_fp32_wrapper=False)`로 accelerate의 autocast 덮개를 벗겨야 검증이 맞습니다.
- 평가 dtype은 고정: preset `torch_dtype`(4B float16) → 없으면 GPU `EVAL_DTYPE`(기본 float16), CPU float32. 지정하지 않으면 transformers 5가 모델 파일의 dtype(Qwen3 bf16, 저장본 fp16)으로 올려 Δ에 정밀도 차이가 섞였습니다. 검색·채점은 numpy float32.
- NaN/inf: 학습 loss면 저장하지 않고 멈춤 → lr 절반 또는 L4/A100. 평가 임베딩이면 `EVAL_DTYPE = "float32"`(기준 모델 결과도 지우고 같은 dtype으로). 평가 OOM이면 `EVAL_BATCH_SIZE` 128/64.
- 2026-10-07 이전 T4 run은 bf16(에뮬레이션)으로 학습됐지만 모델은 유효(느렸을 뿐). 평가만 다시 합니다.

**라이브러리 버전**
- Colab 기본 torch·transformers·sentence-transformers·peft·datasets·accelerate를 **그대로** 씁니다(2026-10 기준 Python 3.13, transformers 5.18, sentence-transformers 5.7, peft 0.21).
  강제로 내리면 huggingface_hub·fsspec까지 내려가 Colab 기본 패키지와 충돌합니다. 추가 설치는 채점용 2개뿐, `torchao`는 peft 0.21과 충돌해 지웁니다.
- API 차이(transformers 5의 `dtype`·`warmup_steps`, ST5의 읽기 전용 `auto_model`·모듈 이동)는 `2. 호환` 셀 / `common.hf_compat`이 흡수.
- 실제 버전은 manifest `environment`, 평가 json `library_versions`, 리더보드 `libs`에 남습니다. Colab 버전이 바뀌면 기준 zero-shot도 그 버전으로 다시 평가해 비교합니다.
- 로컬 설치 범위는 `pyproject.toml`의 `embedding`·`train` extras.
- 예전 ms-swift를 버린 이유: merge한 LoRA에 sentence-transformers 설정(Qwen3 last-token pooling, prompt)이 빠져 **에러 없이 mean pooling으로 로드**됨.

**재현성**
- `train_pairs.jsonl`은 qrels_train + corpus + queries.csv로부터 결정적으로 재생성됩니다. train qrels가 바뀌면 2-1 → 2-2(재업로드) → 재학습.
- seed 20260831 고정이지만 GPU 종류·precision이 다르면 결과가 조금 달라집니다 → manifest `precision`·`environment.gpu`가 같은 run끼리 비교.
- 어떤 코드로 만든 모델인지는 `notebook_code.py`(Colab) / `code_snapshot.zip` + git 커밋(로컬), 어떤 데이터인지는 `data_version`·`training_data.sha256`.
- Qwen3 계열은 query 지시문(`prompt_name="query"`)을 빠뜨리면 업종 쿼리 nDCG가 약 0.15 떨어집니다. bge-m3·Arctic은 지시문 없음.

## 6. 임베딩 v1 선택 결과

**v1 = bge-m3 mj (`bge_m3_ft_mj_20261014_0743`)** — BAAI/bge-m3 full FT, 노트북 기본값 1회, train data `ec3a9b61`(215 query), T4 fp16, 416 step.
모델 `models/bge_m3_ft_mj_20261014_0743/`(git 제외), 설정 `configs/models/bge_m3_ft_mj_20261014_0743.yaml`(prompt 없음, normalize, 1024차원), 기록 `results/finetune_runs/bge_m3_ft_mj_20261014_0743/`.

**val 비교** (124 쿼리, 오타 비활성 + `final_v1_val` 판정 후 qrels, fp16 평가)

| 모델 | nDCG@10 [95% CI] | Judged@10 | top1_ok | bad@3 |
|---|---|---|---|---|
| Qwen3-0.6B zero-shot | 0.920 [0.888, 0.948] | 1.000 | 0.903 | 21/124 |
| bge-m3 zero-shot¹ | 0.918 [0.887, 0.944] | 0.982 | 0.927 | 23/124 |
| Arctic-KO zero-shot¹ | 0.952 [0.926, 0.975] | 0.997 | 0.952 | 9/124 |
| kse16 (Qwen3 0.6B LoRA, hard neg 6) | 0.953 [0.925, 0.976] | 0.999 | 0.968 | 7/124 |
| **bge-m3 mj** (full FT, 기본값) | **0.960 [0.936, 0.980]** | 0.994 | 0.960 | 8/124 |
| Arctic-KO lee (full FT, val HP 탐색 11회 중 1등) | 0.961 [0.937, 0.982] | 0.997 | 0.976 | 6/124 |

¹ depth 20 pooling run이라 판정 누락이 있음. nDCG@10(판정만): bge zero-shot 0.937, Arctic zero-shot 0.957, kse16 0.954, mj 0.966, lee 0.964.

쌍별(paired permutation, nDCG@10): lee vs kse16 +0.008(p=0.28), mj vs kse16 +0.007(p=0.45), lee vs mj +0.001(p=0.84).
학습 효과: kse16 vs Qwen3 zero-shot +0.034(p=0.0001), mj vs bge zero-shot +0.029(판정만 기준, p=0.0005), lee vs Arctic zero-shot +0.008(p=0.025).

**선택 이유**
- 세 후보는 같은 수준(Δ ≤ 0.008, p ≥ 0.28 — Δ ≥ 0.03·p < 0.05 아님). bad@3·top1_ok도 쿼리 1~2개 차이, 크기도 셋 다 약 5.7~6억 파라미터·1024차원.
- 그래서 운영 기준으로 골랐습니다: 기관 공개 베이스(BAAI, MIT)에 우리 판정 데이터만으로 학습해 출처 추적 가능,
  선택 편향 최소(기본값 1회 — kse16 2회, Arctic lee 11회 val 탐색). Arctic-KO는 개인 파인튜닝판·AI Hub 학습 데이터 약관 미확인, Qwen3는 디코더·지시문으로 서빙이 번거로움.
- Arctic lee는 오타 비활성 전 데이터(sha `067e4aa4`, 237 query)·L4 bf16, 30 step·lr 5e-6으로 사실상 zero-shot이고 val 반복 선택으로 낙관 편향.

**서비스 평가셋 재비교 (2026-10-28, 보고용 — 다시 고르지 않음)** — `benchmark/service_ko_v1/eval_set.csv`, test 1km 320 사례, 보충 판정 후 Judged@10 ≥ 0.99:
v1 0.808 ≈ Arctic lee 0.803(p=0.56) ≈ kse16 0.793(p=0.12), bge zero-shot 0.745·char BM25 0.749(둘 다 p<0.001).
차이가 드러난 곳은 지역+업종(D, 32개)뿐: v1 0.793 > Arctic 0.680 > kse16 0.654. → 선택 유지.

**결정 기록(요약)**
- 2026-10-13 오타 증강 채택 안 함 / 2026-10-14 오타 쿼리 49개 비활성(철자 교정 단계로), val 실패 쿼리에 맞춘 데이터 추가 안 함(val 과적합).
- 2026-10-16 Qwen3 hard negative 3→6(kse16) 채택, **v1 = bge-m3 mj**, 추가 HP 탐색·Colab 학습 중단(val 탐색 편향 ≈ +0.008이 후보 차이와 같음).
- 하이브리드·reranker는 임베딩 선택과 분리해 검색 파이프라인 단계에서 평가(`scripts/eval_retrieval_stack.py`, `scripts/eval_service_pipeline.py`).
- 기존 벤치마크 test 1회 채점(`final_v1_test` 라운드)은 계획만 있고 저장소에 결과가 없습니다(`configs/benchmark/judging_candidates.yaml`에 이름만).
