# 팀 학습 가이드 — Colab 노트북 하나로 학습·평가, 결과는 서비스로 이어지게

Arctic(Snowflake)·BGE-M3·Qwen3를 각자 코드와 설정을 바꿔 가며 실험하되, 나중에 **가장 좋았던 모델 폴더 하나와 기록만 보고
검색 서비스·벡터DB에 바로 연결**할 수 있게 하기 위한 절차와 최소 규칙입니다. 설계 배경은 `docs/TRAINING.md`.

> **요약**
> - Colab에서 여는 파일은 **`colab/train_eval.ipynb` 하나**입니다. 학습·평가 코드가 전부 그 안에 있어서 **기법(학습 데이터 만드는 방식,
>   LoRA·loss, 학습 인자)을 노트북 셀에서 바로 고치면** 됩니다. 노트북을 고쳐도 다시 올리는 건 그 파일 하나뿐입니다.
> - Drive에는 **데이터만 한 번** 올립니다(`pack_for_colab.py` → `data/`). 데이터가 바뀔 때만 다시 올립니다.
> - 학습 → val 공식 채점 → 리더보드 → 수정 → 다시 학습을 **전부 Colab 안에서** 반복하고, 실험이 끝나면 결과만 VS Code로 가져와 저장합니다.
> - 사람이 적는 건 **`NOTE` 한 줄**과 (남길 결과일 때) **공유 시트 한 줄**뿐. 나머지는 자동 기록.
> - **평가 셀(채점 로직)과 test split은 아무도 건드리지 않습니다.** 반복 평가는 val로만.

---

## 1. 처음 한 번 — 준비

1. 최신 코드 받기: `git fetch && git switch feature/pooling2-zeroshot && git pull`
2. 데이터 폴더 만들기(로컬 VS Code 터미널):
   ```bash
   python scripts/pack_for_colab.py
   ```
   → `colab_upload/data/` (학습 데이터, corpus, queries, val/test 정답, `data_version.json`, 약 90MB)
3. Drive `내 드라이브/store-search-ai/` 밑에 **`data` 폴더째 업로드**(예전 `project/` 폴더가 있으면 지워도 됩니다 — 더 이상 안 씀).
4. Colab 메뉴 **파일 > 노트북 업로드** → 로컬 저장소의 `colab/train_eval.ipynb` (또는 **GitHub** 탭에서 브랜치 선택).
   메뉴 **런타임 > 런타임 유형 변경**에서 GPU(T4 이상)인지 확인.
5. 설정 셀에서 `OWNER`를 적고 `SMOKE = True`로 둔 채 위에서부터 끝까지 실행 → 맨 아래 `통과`가 나오면 준비 끝(가짜 데이터·축소 코퍼스,
   몇 분, 결과는 `runs_smoke/`라 실제 기록과 안 섞임). 확인 후 `SMOKE = False`로 되돌립니다.

```
내 드라이브/store-search-ai/
  data/         ← pack_for_colab.py 결과 (처음 한 번, 데이터가 바뀔 때만)
  runs/         ← 노트북이 씀: finetune/<TAG>/(모델+기록), model_eval/(검색 결과), evaluation/(지표)
  runs_smoke/   ← SMOKE=True 결과(지워도 됨)
```

## 2. 노트북 구조 — 어디를 고치나

위에서부터 순서대로 실행합니다.

| 셀 | 하는 일 | 고치나? |
|---|---|---|
| GPU 확인 / 설치 / Drive 연결 | 설치는 채점용 2개만, torchao 제거(peft 충돌), HF 라이브러리는 Colab 기본 버전 그대로 | 아니오 |
| **1. 설정** | `OWNER`(필수), `MODEL`, `NOTE`, `SMOKE`, `RESUME_TAG`, `EVAL_RUN_TAG`, `FINAL_TEST` / `MODEL_PRESETS`(모델 목록) / `HP`(학습 설정) | **예** |
| 2. 라이브러리 버전 호환 | transformers 4·5, sentence-transformers 3~5 차이 흡수 + 버전 출력·점검 | 거의 안 함 |
| 3. 데이터 불러오기 | Drive `data/`에서 읽고 학습 데이터·meta 일치 확인 | 아니오 |
| **4. 학습 행 만들기** | (query, positive, negative) 행으로 펼치기 — negative 고르는 방식, 샘플링, 증강 | **예 — 기법 실험** |
| **5. 모델·loss** | LoRA 설정, loss(GIST/MNRL/…), Matryoshka | **예 — 기법 실험** |
| 6. 학습 루프·저장·기록 | Trainer 인자, 체크포인트, 저장·검증, manifest, 오래된 run 정리 | 학습 인자(scheduler 등)만 |
| **7. 평가** | 공식 evaluator와 같은 채점 로직 | **아니오 — 절대 고치지 않음** |
| 8. 학습 | `train_model(...)` 실행 | 아니오 |
| 9. 평가 (val) | 기준 zero-shot 모델(처음 한 번 자동) + 학습한 모델 채점, 기준 대비 Δ·p-value | 아니오 |
| 10. 리더보드 | Drive에 쌓인 평가 전부, nDCG@10 순 | 아니오 |
| 11. zero-shot 비교표 | `ZERO_SHOT_MODELS` 목록을 한 번에 평가 | 목록만 |
| 12. SMOKE 확인 | `SMOKE=True`일 때 전체 흐름 점검, `통과`/`FAIL` | 아니오 |
| 13. KEEP | 남길 run 표시 | TAG만 |
| 14. test 평가 | `FINAL_TEST=True`일 때만 | 최종 후보 확정 후에만 |

| 바꾸려는 것 | 어디 |
|---|---|
| epoch, batch, lr, loss 종류, negative 개수, LoRA r 등 숫자 | `1. 설정`의 `HP` |
| 새 모델 추가 | `1. 설정`의 `MODEL_PRESETS`에 한 항목 |
| negative를 고르는 방식, 학습 행 샘플링·증강 | `4. 학습 행` |
| 새 loss, LoRA 대상 모듈, pooling | `5. 모델·loss` |
| scheduler, gradient accumulation 등 Trainer 인자 | `6. 학습 루프`의 `train_model` 안 |
| positive/negative 후보 자체(학습 데이터 재생성) | 저장소 `src/store_search_ai/data/finetune_dataset.py` — 데이터 담당과 상의(부록) |

**코드를 고친 뒤**: 고친 셀을 다시 실행 → **8. 학습부터** 다시 실행(세션 재시작 불필요).
학습할 때마다 그 세션에서 실행한 셀 코드 전체가 모델 폴더의 **`notebook_code.py`**에 자동 저장됩니다 — 셀을 고쳐 가며 실험해도
어떤 코드로 만든 모델인지 그대로 남습니다(따로 커밋하지 않아도 기록은 남음).

좋은 기법을 팀 기본값으로 만들 때는 수정한 `.ipynb`를 내려받아(파일 > 다운로드) 저장소 `colab/train_eval.ipynb`에 커밋합니다.
이때 `7. 평가` 셀이 바뀌었으면 `tests/test_train_eval_notebook.py`가 실패합니다(채점이 공식 evaluator와 같아야 함).

## 3. 반복 루프

```
설정·기법 수정 → 8. 학습 → 9. 평가(val, 기준 대비 Δ·p) → 10. 리더보드 확인
  → 남길 결과면 13. KEEP + 공유 시트 한 줄 / 아니면 다시 수정
```

- 학습 없이 기존 run만 다시 평가: `EVAL_RUN_TAG = "<TAG>"` 넣고 8번은 건너뛰고 9번부터.
- Colab이 끊김: 로그에 `[체크포인트] … 저장 완료`가 나온 뒤였다면 `RESUME_TAG = "<TAG>"`, **다른 설정은 처음과 똑같이** 두고 처음부터
  실행(설치·Drive 연결 → … → 8번). 그 전이면 처음부터 다시 학습.
- 처음 써 보는 설정(특히 4B, 큰 batch)은 `SMOKE=True`로 메모리·속도를 먼저 확인해도 됩니다.

## 4. 기록 — 딱 세 군데

| 어디 | 누가 | 언제 | 무엇을 |
|---|---|---|---|
| **`model_manifest.json`** (Drive `runs/finetune/<TAG>/`) | **자동** | 학습·평가할 때마다 | 설정 전부(`HP`·preset), 학습 데이터 해시, 데이터 버전, 코드 사본(`notebook_code.py`), GPU·라이브러리 버전, 서비스가 따라야 할 값(`serving`), 평가 결과 — **손대지 않음** |
| **설정 셀의 `NOTE`** | 나 | 기본값에서 무언가 바꿨을 때 | 무엇을 왜 바꿨는지 한 줄 |
| **공유 시트** | 나 | val 평가 후, **남길 run만** | run 하나당 한 줄(7절) |

**`NOTE` 쓰는 법**
```python
NOTE = "negative 3→5개, 어려운 negative 효과 확인"
NOTE = "4. 학습 행: relevance=1 negative 제외"
NOTE = "서비스도 필요: 쿼리 특수문자 제거 후 인코딩"   # 모델 밖 처리를 넣었을 때는 반드시 이렇게 시작
```
**모델 밖에서 하는 처리**(쿼리·문서 전처리, BM25 hybrid, reranker 등)는 모델 폴더에 저장되지 않아서 서비스에서도 똑같이 다시 해야 합니다.
이런 처리를 넣었으면 `NOTE`를 `서비스도 필요:`로 시작하고, 그 코드는 서비스로 옮길 수 있게 함수로 분리해 두세요.

처음 몇 번은 학습이 끝까지 도는지·시간·메모리만 보는 시험 run이어도 괜찮습니다(manifest는 자동으로 남음). 시트·KEEP은 **남길 run만**.

## 5. 절대 바꾸지 않는 것

- **`7. 평가` 셀**(채점 로직), 정답 파일(Drive `data/`의 qrels·queries·corpus — 데이터 담당이 배포한 것만).
- **test split은 보지 않습니다.** 모든 선택은 val로. test는 팀이 최종 후보를 정한 뒤 `FINAL_TEST = True`로 한 번만.
- 채점 방식을 바꿔야 한다면 팀 합의 후 저장소의 공식 evaluator부터 바꾸고 모든 run을 다시 채점합니다.

## 6. KEEP — 지우면 안 되는 run 표시

Drive는 학습이 끝날 때마다 **내 run 중 같은 모델의 최신 3개(`HP["keep_last_runs"]`)만 남기고 자동 삭제**합니다(다른 사람 run은 안 건드림).
남길 run은 `13. KEEP` 셀의 주석을 풀고 TAG를 바꿔 실행 → 그 폴더에 빈 `KEEP` 파일이 생겨 삭제되지 않습니다.
KEEP 기준: **모델별 baseline run / 공유 시트에 올린 run / 서비스 후보·발표용**.

## 7. 공유 시트 (남길 run만 한 줄)

팀 공유 Drive에 Google Sheets를 하나 만들고 첫 줄에 붙여넣기(탭 구분):
```
TAG	이름	베이스모델	NOTE	학습데이터해시	GPU	precision	libs	nDCG@10	Judged@10	Recall@100	ΔnDCG@10	p-value	KEEP
```
값은 `9. 평가` 출력과 `10. 리더보드`(Δ·p·libs), manifest(`training_data.sha256`, `environment.gpu`, `precision`)에서 복사합니다.

**숫자 읽는 법**
- val은 136개 쿼리라 nDCG@10에 ±0.05 정도 오차가 있습니다. **차이가 0.03보다 작거나 p가 크면 "개선"이라 하지 않습니다.**
- **Judged@10**(상위 10개 중 정답 판정이 있는 비율)이 낮으면 점수가 실제보다 낮게 나왔을 수 있습니다(정답이 키워드 검색 pool로 만들어져
  모델이 새로 찾은 문서는 판정이 없어 오답으로 계산).
- **같은 학습 데이터 해시 + 같은 precision(T4=fp16, L4/A100=bf16) + 같은 `libs`**끼리만 비교합니다. Colab이 기본 라이브러리를 올렸으면
  기준 zero-shot 모델도 그 버전으로 다시 평가해서 비교합니다(그 모델의 `runs/model_eval/<이름>/` 폴더를 지우고 9번 실행).

## 8. 실험이 끝나면 — VS Code로 가져와 저장

1. 웹 Google Drive에서 `내 드라이브/store-search-ai` 폴더 다운로드 → 압축 해제(`runs/`만 있으면 됨).
2. 로컬 저장소 루트에서:
   ```bash
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --dry-run   # 무엇을 옮길지 확인
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --verify
   ```
   - 평가 결과 → `results/model_eval/`, `artifacts/evaluation/storesearch_ko_v1/` (SMOKE 같은 비공식 평가는 자동 제외)
   - **KEEP 표시한 run**만 → `models/<TAG>/` + `configs/models/<TAG>.yaml` (특정 run만: `--models <TAG> ...`)
   - `--verify`: 로컬 공식 evaluator로 다시 채점해 Colab 점수와 같은지 확인(다르면 종료코드 1)
3. `git add results/ artifacts/ configs/models/` → 커밋. 좋은 기법이 들어간 노트북도 `colab/train_eval.ipynb`로 커밋.
   (`models/`는 용량 때문에 .gitignore — 서비스 후보 모델은 팀 공유 스토리지에 따로 보관)

## 9. 서비스에 쓸 수 있는 상태인지

서비스는 `SentenceTransformer(모델폴더)` 한 줄로 모델을 불러옵니다. 노트북은 LoRA를 merge한 전체 모델을 sentence-transformers 형식으로
저장하고, 저장 직후 다시 불러와 임베딩이 같은지 검증합니다(`[검증] … 일치 확인`). 그리고 manifest의 `serving`(query prompt, 차원, normalize,
문서 template)을 서비스가 그대로 따르면 됩니다. BGE-M3의 sparse/multi-vector처럼 **벡터 하나로 표현되지 않는 방식**은 벡터DB 구조가
달라지므로 시작 전에 팀에 공유합니다.

## 10. 막히면

| 증상 | 조치 |
|---|---|
| `ImportError: … torchao …` | 설치 셀(`pip uninstall -y torchao`)이 실행됐는지 확인. 이미 torch를 import한 뒤라면 런타임 > 세션 다시 시작 후 처음부터 |
| `ModuleNotFoundError: ir_measures` | 설치 셀 다시 실행 |
| `Colab 환경 문제: …` (2번 셀) | 메시지대로 패키지 설치. `[경고] 확인된 적 없는 메이저 버전`이면 `SMOKE=True`로 먼저 확인 |
| `No such file … data/…` | Drive `store-search-ai/data/`에 `pack_for_colab.py` 결과를 올렸는지 확인 |
| `train_pairs.jsonl과 meta.json이 맞지 않습니다` | `pack_for_colab.py`로 다시 만들어 `data/`째 다시 올리기 |
| `CUDA out of memory` | `HP["batch_size"]`를 16(4B는 4)으로, 또는 `HP["loss"] = "mnrl"` → `NOTE`에 적기 |
| `loss가 NaN/inf` | 저장된 것 없음. `learning_rate`를 절반으로, 또는 bf16 GPU(L4/A100) |
| `처음 실행과 설정/데이터가 다릅니다` | `RESUME_TAG`로 이어 할 때는 처음 설정 그대로 |
| `test split은 최종 후보를 정한 뒤 한 번만` | 정상 — 반복 실험은 val로만 |
| 평가가 오래 걸림 | 문서 21만 개 인코딩(모델당 수 분~수십 분). 기준 zero-shot은 처음 한 번만 |
| `OWNER를 … 적으세요` | 영문 소문자로 시작하는 2~16자(소문자·숫자) |

그 밖의 오류는 **traceback 전체**를 복사해서 공유하세요.

---

## 부록. 데이터 담당 — 학습 데이터·정답 배포

1. train 애노테이션 반영(`docs/PIPELINE.md` 4절) → `python scripts/prepare_finetune_dataset.py`
2. `data/finetune/train_pairs.jsonl`과 `train_pairs.meta.json`을 **같이** 커밋·push
3. 정답(qrels)이 바뀌면 `11_build_qrels.py` → `12_validate_benchmark.py --stage final` → 커밋·push
4. `python scripts/pack_for_colab.py`로 `data/`를 만들어 팀 공유 위치에 올리고 공지(커밋 번호, `train_pairs_sha256` 앞 8자리)
5. 데이터가 바뀌면 다시 공지 — 다른 데이터로 학습한 run끼리는 비교하지 않습니다(리더보드·manifest의 데이터 해시로 구분)
