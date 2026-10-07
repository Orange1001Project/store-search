# 팀 학습 가이드 — Colab 노트북 하나로 학습·평가, 결과는 서비스로 이어지게

Arctic(Snowflake)·BGE-M3·Qwen3를 각자 코드와 설정을 바꿔 가며 실험하되, 나중에 **가장 좋았던 모델 폴더 하나와 기록만 보고
검색 서비스·벡터DB에 바로 연결**할 수 있게 하기 위한 절차와 최소 규칙입니다. 설계 배경은 `docs/TRAINING.md`.

> **요약**
> - Colab에서 여는 파일은 **`colab/train_eval.ipynb` 하나**입니다. 학습·평가 코드가 전부 그 안에 있어서 **기법(학습 데이터 만드는 방식,
>   LoRA·loss, 학습 인자)을 노트북 셀에서 바로 고치면** 됩니다. 노트북을 고쳐도 다시 올리는 건 그 파일 하나뿐입니다.
> - Drive에는 **데이터만 한 번** 올립니다(`pack_for_colab.py` → `data/`). 데이터가 바뀔 때만 다시 올립니다.
> - 노트북 수정은 두 가지: **A. Colab에서 바로**(작은 수정, 세션 유지) / **B. VS Code(Claude)에서 고쳐 다시 업로드**(큰 수정).
>   정본은 저장소 `colab/train_eval.ipynb` — Colab에서 고쳤으면 내려받아 덮어쓴 뒤 VS Code에서 고칩니다(3절).
> - 학습 → val 공식 채점 → 리더보드 → 수정 → 다시 학습을 **전부 Colab 안에서** 반복하고, 실험이 끝나면 결과만 VS Code로 가져와 저장합니다.
> - 사람이 하는 건 **`NOTE` 한 줄**과 남길 run의 **KEEP 표시**뿐. 실험 기록표(`results/experiments.csv`)는 결과를 가져올 때 자동으로 채워집니다.
> - **평가 셀(채점 로직)과 test split은 아무도 건드리지 않습니다.** 반복 평가는 val로만.

---

## 1. 처음 한 번 — 준비 (데이터는 한 번만 올림)

1. 최신 코드 받기(로컬 VS Code 터미널): `git fetch && git switch feature/pooling2-zeroshot && git pull`
2. 데이터 폴더 만들기:
   ```bash
   python scripts/pack_for_colab.py
   ```
   → `colab_upload/data/` (학습 데이터, corpus, queries, val/test 정답, `data_version.json`, 약 90MB)
3. 웹 Google Drive에서 `내 드라이브/store-search-ai/` 폴더를 만들고 그 밑에 **`data` 폴더째 업로드**.
   예전 `project/` 폴더가 있으면 지워도 됩니다(더 이상 안 씀). **이후에는 데이터 담당이 데이터를 바꿨다고 공지할 때만** 다시 올립니다.
4. Colab(colab.research.google.com) 메뉴 **파일 > 노트북 업로드** → 로컬 저장소의 `colab/train_eval.ipynb` 선택.
   - 업로드한 노트북은 Drive `내 드라이브/Colab Notebooks/train_eval.ipynb`에 사본으로 저장되고, Colab에서 고치면 그 사본이 자동 저장됩니다.
   - 메뉴 **런타임 > 런타임 유형 변경**에서 GPU(T4 이상)인지 확인.
5. 설정 셀에서 `OWNER`를 적고 `SMOKE = True`로 둔 채 **런타임 > 모두 실행** → 맨 아래 `통과`가 나오면 준비 끝
   (가짜 데이터·축소 코퍼스, 결과는 `runs_smoke/`라 실제 기록과 안 섞임). 확인 후 `runs_smoke/`는 지워도 됩니다.

```
내 드라이브/
  Colab Notebooks/train_eval.ipynb   ← Colab이 쓰는 노트북 사본(업로드할 때 생김)
  store-search-ai/
    data/         ← pack_for_colab.py 결과 (처음 한 번, 데이터가 바뀔 때만)
    runs/         ← 노트북이 씀: finetune/<TAG>/(모델+기록), model_eval/(검색 결과), evaluation/(지표)
    runs_smoke/   ← SMOKE=True 결과(지워도 됨)
```

## 2. 노트북 구조 — 어디를 고치나

위에서부터 순서대로 실행합니다. 셀 하나하나의 코드 설명은 **`docs/TRAIN_EVAL_NOTEBOOK.md`**.

| 셀 | 하는 일 | 고치나? |
|---|---|---|
| GPU 확인 / 설치 / Drive 연결 | 설치는 채점용 2개만, torchao 제거(peft 충돌), HF 라이브러리는 Colab 기본 버전 그대로 | 아니오 |
| **1. 설정** | `OWNER`(필수), `MODEL`, `NOTE`, `SMOKE`, `RESUME_TAG`, `SAVE_MID_CHECKPOINT`, `EVAL_RUN_TAG`, `FINAL_TEST` / `MODEL_PRESETS`(모델 목록) / `HP`(학습 설정) | **예** |
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

## 3. 노트북 고치기 — 두 가지 방법

데이터는 Drive에 그대로 두고 **노트북만** 고칩니다. 수정 규모에 따라 둘 중 하나를 고르세요.

| | A. Colab에서 바로 고치기 | B. VS Code(Claude)에서 고치고 다시 올리기 |
|---|---|---|
| 언제 | 값 몇 개, 한두 줄 수정 | 함수를 새로 쓰거나 여러 셀을 고칠 때, Claude에게 맡길 때 |
| 세션 | **유지**(데이터·모델 다시 안 불러옴) | **새 세션**(위에서부터 다시 실행) |
| 정본 맞추기 | 끝나고 Colab 노트북을 내려받아 저장소 파일에 덮어쓰기 | 저장소 파일이 이미 최신 |

**정본은 저장소의 `colab/train_eval.ipynb` 하나입니다.** Colab에서 고친 내용은 Drive의 사본에만 있으므로, 다음에 VS Code에서 고치기 전에
반드시 **Colab 메뉴 파일 > 다운로드 > .ipynb 다운로드**로 받아 저장소 `colab/train_eval.ipynb`에 덮어쓰세요. 안 그러면 Claude가 옛 버전을
고쳐서 Colab에서 고친 내용이 사라집니다.

### A. Colab에서 바로 고치기 (세션 유지)

1. 고칠 셀을 Colab에서 직접 수정.
2. **아래 "다시 실행할 셀" 표**대로 실행(보통 고친 셀 → 8 → 9 → 10).
3. 실험이 끝나면(또는 VS Code에서 고치기 전에) 파일 > 다운로드 > .ipynb → 저장소 `colab/train_eval.ipynb`에 덮어쓰기.

VS Code의 Claude에게 "이 셀을 이렇게 바꿔 줘"라고 해서 **바뀐 셀 코드만 받아 Colab 셀에 붙여넣는 것**도 A 방법입니다
(세션을 유지한 채 Claude의 수정을 쓸 수 있음 — 이때는 저장소 파일도 Claude가 이미 고쳤으므로 다운로드할 필요 없음).

### B. VS Code(Claude)에서 고치고 다시 올리기 (새 세션)

1. (A로 고친 게 있으면 먼저 내려받아 덮어쓰기)
2. VS Code에서 Claude에게 `colab/train_eval.ipynb` 수정을 요청 → 저장.
3. 웹 Google Drive에서 `내 드라이브/Colab Notebooks/train_eval.ipynb`(이전 사본)를 **삭제** — 같은 이름이 여러 개 생겨 헷갈리는 것 방지.
4. 지금 Colab 탭에서 **런타임 > 런타임 연결 해제 및 삭제**(GPU 반납) 후 탭 닫기.
5. Colab **파일 > 노트북 업로드** → 고친 `colab/train_eval.ipynb`.
6. 설정 셀 확인(`OWNER`·`MODEL`·`NOTE`·`SMOKE`) → **런타임 > 모두 실행**(또는 위에서부터 차례로).
   큰 수정이면 `SMOKE = True`로 먼저 한 번 돌려 `통과`를 확인한 뒤 `SMOKE = False`로 실제 학습.

### 다시 실행할 셀 (세션을 유지할 때)

번호는 노트북의 제목 번호(`## 1. 설정`, `## 8. 학습` …)이고, 각 제목 바로 아래 코드 셀을 실행한다는 뜻입니다.
함수만 정의하는 셀(2·4·5·6·7)은 **고쳤을 때만** 다시 실행하면 됩니다. 함수들은 설정·데이터 값을 호출하는 순간 읽기 때문입니다.

| 바꾼 것 | 다시 실행할 셀 (순서대로) |
|---|---|
| `HP`, `NOTE`, `MODEL` (설정 셀) | 1 → 8 → 9 → 10 |
| `SMOKE` (True↔False) | 1 → **3** → 8 → 9 → 10 (데이터가 바뀌므로 3번 필수) |
| 4. 학습 행 / 5. 모델·loss / 6. 학습 루프 | 고친 셀 → 8 → 9 → 10 |
| 학습 없이 기존 run 평가 | 1(`EVAL_RUN_TAG` 설정) → 9 → 10 |
| Drive `data/`를 새로 올림 | 1 → 3 → 8 → 9 → 10 (기준 zero-shot도 새 데이터로 다시 평가해야 하면 `runs/model_eval/<기준이름>/` 삭제) |
| 학습 셀(8)이 OOM·에러로 실패 | 런타임 > **세션 다시 시작** → 위에서부터 전부 |
| 노트북을 새로 업로드(B) | 위에서부터 전부 |

## 4. 실행 순서 — 학습 한 번의 전체 흐름

```
[세션 시작]  GPU 확인 → 설치 → Drive 연결 → 1. 설정 → 2. 호환 → (환경 점검) → 3. 데이터 → 4·5·6·7 (함수 정의)
[학습]       8. 학습      … 0.6B 기준 T4에서 약 1시간 (로그: [체크포인트] → [검증] … 일치 확인 → [완료] 최종 모델)
[평가]       9. 평가      … 처음엔 기준 zero-shot도 평가(문서 21만 개 인코딩, 수십 분)
[비교]       10. 리더보드  … 기준 대비 ΔnDCG@10, p-value
[정리]       남길 run이면 13. KEEP (7절) — 기록표는 마지막에 가져올 때 자동(8·9절)
[다음 실험]  3절 방법 A 또는 B로 고치고 → 표대로 다시 실행
```

- 학습 없이 기존 run만 다시 평가: `EVAL_RUN_TAG = "<TAG>"` 넣고 8번은 건너뛰고 9번부터.
- Colab이 끊김: 로그에 `[체크포인트] … 저장 완료`가 나온 뒤였다면 `RESUME_TAG = "<TAG>"`, **다른 설정은 처음과 똑같이** 두고 처음부터
  실행. 그 전이면 처음부터 다시 학습. 끊긴 run의 `<TAG>.ckpt` 폴더는 이어 하지 않을 거면 지워도 됩니다.
- 학습 셀이 끝나지 않았는데(실패·중단) 9번을 실행하면 "8. 학습이 끝나지 않았습니다"로 멈춥니다(정상 — 같은 세션의 이전 run을
  잘못 평가하지 않게 8번이 시작할 때 `final_dir`을 비움).
- 처음 써 보는 설정(특히 4B, 큰 batch)은 `SMOKE=True`로 메모리·속도를 먼저 확인해도 됩니다.

### 런타임이 끊겼을 때 — 어디부터 다시?

끊기면 메모리(설치·변수·함수·`final_dir`)는 전부 사라지고 **Drive에 쓴 파일만 남습니다.** 그래서 다시 연결하면 항상 설치·Drive 연결·설정·
함수 정의 셀부터 다시 실행합니다. 상황은 Drive `runs/finetune/` 폴더로 판단합니다.

| 끊긴 시점 | Drive `runs/finetune/`에 보이는 것 | 다시 연결 후 |
|---|---|---|
| 학습 중, `[체크포인트] … 저장 완료` **전** | `<TAG>.ckpt`(안에 `checkpoint-숫자` 없음) | `<TAG>.ckpt` 삭제 → 설정 그대로 **런타임 > 모두 실행**(새로 학습) |
| 학습 중, 체크포인트 **후** | `<TAG>.ckpt/checkpoint-숫자/` | `RESUME_TAG = "<TAG>"`, 다른 설정은 처음과 똑같이 → **모두 실행**(남은 절반만) |
| 저장·검증 중(`[완료]` 전) | `<TAG>.partial` + `<TAG>.ckpt` | 위와 같이 `RESUME_TAG` → **모두 실행**(`.partial`은 자동 삭제) |
| **학습 완료 후 ~ 9. 평가 중** | `<TAG>`(접미사 없음, 안에 `model_manifest.json`) | `EVAL_RUN_TAG = "<TAG>"` → **모두 실행**(8번 학습은 자동으로 건너뛰고 9번 평가부터) |
| 평가까지 끝난 뒤 | `runs/evaluation/<TAG>_t1_minimal_val_evaluation.json` 있음 | 할 것 없음. 리더보드만 보려면 7. 평가 셀까지 실행 후 10번 |

- TAG는 로그의 `[INFO] run: <TAG>`·`[완료] 최종 모델: …/<TAG>` 또는 Drive 폴더 이름(`.ckpt`·`.partial` 뗀 것).
- "모두 실행"이 안전한 이유: `EVAL_RUN_TAG`가 있으면 8번은 학습하지 않고, 11·12·14번은 기본값에서 아무것도 하지 않습니다.
- 셀을 골라 평가만 하려면: GPU 확인 → 설치 → Drive 연결 → 1. 설정(`EVAL_RUN_TAG`) → 2. 호환+점검 → 3. 데이터 → 4·5·6·7(함수 정의) → 9 → 10.
  함수 정의 셀을 빼면 `NameError`가 납니다.
- 기준 zero-shot 평가 중에 끊겼으면 9번이 알아서 다시 평가합니다. 기준 모델 줄이 리더보드에 안 보이면 `runs/model_eval/<기준이름>/`을
  지우고 9번을 다시 실행.

- 학습할 때마다 그 세션에서 실행한 셀 코드 전체가 모델 폴더의 **`notebook_code.py`**에 자동 저장됩니다 — A 방법으로 셀을 고쳐 가며
  실험해도 어떤 코드로 만든 모델인지 그대로 남습니다.
- 좋은 기법을 팀 기본값으로 만들 때는 저장소 `colab/train_eval.ipynb`를 커밋·push합니다. 이때 `7. 평가` 셀이나 `4. 학습 행`의 기본 동작이
  바뀌었으면 `tests/test_train_eval_notebook.py`가 실패합니다(의도한 변경이면 테스트도 같이 고침).

## 5. 기록 — 딱 세 군데

| 어디 | 누가 | 언제 | 무엇을 |
|---|---|---|---|
| **`model_manifest.json`** (Drive `runs/finetune/<TAG>/`) | **자동** | 학습·평가할 때마다 | 설정 전부(`HP`·preset), 학습 데이터 해시, 데이터 버전, 코드 사본(`notebook_code.py`), GPU·라이브러리 버전, 서비스가 따라야 할 값(`serving`), 평가 결과 — **손대지 않음** |
| **설정 셀의 `NOTE`** | 나 | 기본값에서 무언가 바꿨을 때 | 무엇을 왜 바꿨는지 한 줄 |
| **실험 기록표** `results/experiments.csv` (저장소) | **자동** | 결과를 가져올 때(9절) | 평가 하나당 한 줄 — manifest·평가 json에서 채움(8절) |

**`NOTE` 쓰는 법**
```python
NOTE = "negative 3→5개, 어려운 negative 효과 확인"
NOTE = "4. 학습 행: relevance=1 negative 제외"
NOTE = "서비스도 필요: 쿼리 특수문자 제거 후 인코딩"   # 모델 밖 처리를 넣었을 때는 반드시 이렇게 시작
```
**모델 밖에서 하는 처리**(쿼리·문서 전처리, BM25 hybrid, reranker 등)는 모델 폴더에 저장되지 않아서 서비스에서도 똑같이 다시 해야 합니다.
이런 처리를 넣었으면 `NOTE`를 `서비스도 필요:`로 시작하고, 그 코드는 서비스로 옮길 수 있게 함수로 분리해 두세요.

처음 몇 번은 학습이 끝까지 도는지·시간·메모리만 보는 시험 run이어도 괜찮습니다(manifest는 자동으로 남음). KEEP은 **남길 run만**.

## 6. 절대 바꾸지 않는 것

- **`7. 평가` 셀**(채점 로직), 정답 파일(Drive `data/`의 qrels·queries·corpus — 데이터 담당이 배포한 것만).
- **test split은 보지 않습니다.** 모든 선택은 val로. test는 팀이 최종 후보를 정한 뒤 `FINAL_TEST = True`로 한 번만.
- 채점 방식을 바꿔야 한다면 팀 합의 후 저장소의 공식 evaluator부터 바꾸고 모든 run을 다시 채점합니다.

## 7. KEEP — 지우면 안 되는 run 표시

KEEP은 문서에 적는 게 아니라 **Drive의 그 run 폴더 안에 `KEEP`이라는 빈 파일을 만드는 것**입니다. 하는 일은 두 가지:
- Drive 자동 정리에서 빠짐 — 학습이 끝날 때마다 **내 run 중 같은 모델의 최신 3개(`HP["keep_last_runs"]`)만 남기고 지우는데**, KEEP 파일이 있는
  run은 지우지 않고 3개에도 세지 않습니다(다른 사람 run은 원래 안 건드림).
- 결과를 가져올 때(9절) **KEEP한 run만 모델 가중치까지** `models/<TAG>/`로 복사되고 실험 기록표의 `keep` 열이 `True`가 됩니다.

**하는 법** — Colab 노트북 `13. KEEP` 셀의 주석(`#`)을 지우고 TAG를 넣어 실행합니다(Drive 화면에서는 빈 파일을 만들 수 없어서 이 한 줄로):
```python
(FINETUNE_DIR / "qwen3_embedding_0_6b_ft_kse1_20261006_0708" / "KEEP").touch()
```
런타임을 새로 연결했다면 설치·Drive 연결·`1. 설정` 셀을 먼저 실행해야 `FINETUNE_DIR`이 생깁니다. 확인: Drive `runs/finetune/<TAG>/`에 `KEEP` 파일이
보이면 됩니다. 취소는 그 파일을 Drive에서 지우면 됩니다. **Drive를 내려받기 전에** 표시해야 가져오기에 반영됩니다.

KEEP 기준: **모델별 baseline run / 서비스 후보 / 발표·비교에 계속 쓸 run**.

## 8. 실험 기록표 — `results/experiments.csv` (저장소 안, 자동)

팀 실험 기록은 외부 시트가 아니라 **저장소의 `results/experiments.csv`** 하나입니다. 9절의 가져오기 스크립트가 Drive의 공식 평가마다 한 줄씩
자동으로 채우므로 사람이 옮겨 적을 필요가 없고, 커밋하면 팀 전체가 같은 표를 봅니다.

| 열 | 출처 |
|---|---|
| `eval_tag`, `model`, `kind`(zero-shot / fine-tuned) | 평가 json |
| `owner`, `base_model`, `note`, `train_data_sha8`, `gpu`, `precision` | 그 run의 `model_manifest.json` |
| `eval_dtype`, `libs`, `nDCG@10`, `Judged@10`, `Recall@100`, `MRR@100`, `Bpref`, `delta_nDCG@10`, `p_nDCG@10`, `baseline` | 평가 json |
| `keep` | Drive run 폴더의 `KEEP` 파일(또는 `--models`로 고른 run) |
| `evaluated_at` | 평가 json |

- 같은 `eval_tag`를 다시 가져오면 그 줄만 새 값으로 바뀌고, 예전에 가져온 다른 줄(Drive에서 정리돼 지워진 run 포함)은 남습니다.
- 모든 fine-tuned run의 기록 파일(`model_manifest.json`, `eval_config.yaml`, `notebook_code.py`)도 `results/finetune_runs/<TAG>/`로 저장돼
  git에 남습니다 — 모델 가중치(`models/`)는 용량 때문에 git에 안 올라가므로, "어떤 설정·데이터·코드로 만든 run인지"는 여기서 봅니다.
- 실험 중간에 팀원에게 빨리 공유하고 싶으면 Colab `10. 리더보드` 출력을 복사해 공유해도 되지만, 공식 기록은 이 표입니다.

**숫자 읽는 법**
- val은 136개 쿼리라 nDCG@10에 ±0.05 정도 오차가 있습니다. **차이가 0.03보다 작거나 p가 크면 "개선"이라 하지 않습니다.**
- **Judged@10**(상위 10개 중 정답 판정이 있는 비율)이 낮으면 점수가 실제보다 낮게 나왔을 수 있습니다(정답이 키워드 검색 pool로 만들어져
  모델이 새로 찾은 문서는 판정이 없어 오답으로 계산).
- **같은 학습 데이터 해시 + 같은 precision(T4=fp16, L4/A100=bf16) + 같은 `eval_dtype` + 같은 `libs`**끼리만 비교합니다.
  리더보드 `eval_dtype`이 비어 있는 결과는 평가 정밀도를 고정하기 전(2026-10-07 이전) 것이라 다시 평가합니다. 정밀도 설명은 `docs/TRAINING.md` 6절. Colab이 기본 라이브러리를 올렸으면
  기준 zero-shot 모델도 그 버전으로 다시 평가해서 비교합니다(그 모델의 `runs/model_eval/<이름>/` 폴더를 지우고 9번 실행).

## 9. 실험이 끝나면 — VS Code로 가져와 저장

1. 웹 Google Drive에서 `내 드라이브/store-search-ai` 폴더 다운로드 → 압축 해제(`runs/`만 있으면 됨).
2. 로컬 저장소 루트에서:
   ```bash
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --dry-run   # 무엇을 옮길지 확인
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --verify
   ```
   **`results/` 밑에 폴더를 손으로 복사하지 마세요** — 이 스크립트가 정해진 자리로 나눠 넣고 검증·기록까지 합니다:

   | Drive `store-search-ai/runs/` | → 저장소 | git |
   |---|---|---|
   | `model_eval/<이름>/run_*.csv` (검색 결과) | `results/model_eval/<이름>/` | 커밋 |
   | `evaluation/*_evaluation.json`, `*_per_query.csv` (지표) | `artifacts/evaluation/storesearch_ko_v1/` | 커밋 |
   | `finetune/<TAG>/`의 manifest·eval_config·notebook_code (모든 run) | `results/finetune_runs/<TAG>/` | 커밋 |
   | (자동 생성) 평가마다 한 줄 | `results/experiments.csv` | 커밋 |
   | `finetune/<TAG>/` 모델 전체 — **KEEP한 run만**(또는 `--models <TAG> ...`) | `models/<TAG>/` | 안 함(.gitignore, 용량) |
   | 그 run의 `eval_config.yaml` | `configs/models/<TAG>.yaml` | 커밋 |

   - SMOKE 같은 비공식 평가는 자동으로 빠집니다(`runs_smoke/`는 내려받지 않아도 됨).
   - `--verify`: 가져온 평가를 로컬 공식 evaluator로 다시 채점해 Colab 점수와 같은지 확인(다르면 종료코드 1).
3. `git add results/ artifacts/ configs/models/` → 커밋. 좋은 기법이 들어간 노트북도 `colab/train_eval.ipynb`로 커밋.
   서비스 후보 모델(`models/<TAG>/`)은 팀 공유 스토리지에 따로 보관합니다.

## 10. 서비스에 쓸 수 있는 상태인지

서비스는 `SentenceTransformer(모델폴더)` 한 줄로 모델을 불러옵니다. 노트북은 LoRA를 merge한 전체 모델을 sentence-transformers 형식으로
저장하고, 저장 직후 다시 불러와 학습된 모델과 임베딩이 같은지 검증합니다(`[검증] 저장본(float16) … 일치 확인`). fp16으로 저장하면 임베딩이 달라지는 경우엔 자동으로 float32로 다시 저장합니다(`[경고] … float32로 다시 저장합니다`, manifest `serving.saved_dtype`). 그리고 manifest의 `serving`(query prompt, 차원, normalize,
문서 template)을 서비스가 그대로 따르면 됩니다. BGE-M3의 sparse/multi-vector처럼 **벡터 하나로 표현되지 않는 방식**은 벡터DB 구조가
달라지므로 시작 전에 팀에 공유합니다.

## 11. 성능 올리기 — 모델별 방향 (일단 방향만)

먼저 **기본값 baseline run 하나**(KEEP)를 만들고, 아래를 **한 번에 하나씩** 바꿔 val Δ·p로 판단합니다(차이 0.03 미만이면 개선 아님).

| 모델 | 출발점 | 먼저 해 볼 것 |
|---|---|---|
| **Arctic-ko** (`arctic_ko`, `arctic_ko_query`) | 예전 zero-shot 중 가장 높았음(nDCG@10 0.47) | ① `arctic_ko_query`(학습 때 쓴 `query: ` 접두어)와 비교 ② 이미 강하므로 **망가뜨리지 않게** lr 1e-5·epoch 1 ③ negative 3→5 |
| **BGE-M3** (`bge_m3`) | 0.39 | ① lr 1e-5~2e-5, epoch 1~3 ② negative 3→5 ③ 서비스에서 dense만 쓸지, sparse(키워드형)까지 쓸지 결정(벡터DB 구조가 달라짐 — 팀 공유) |
| **Qwen3-0.6B** (`qwen3_0_6b`, `_store`) | 0.34(가장 낮게 출발) | ① **prompt**: `qwen3_0_6b_store`(매장 검색용 지시문) — 지시문 모델이라 효과가 큼 ② LoRA r 16→32/64, lr 5e-5~2e-4 ③ `loss="mnrl"`과 GIST 비교 |
| **Qwen3-4B** (`qwen3_4b`, `_store`) | – | T4는 빠듯함 → 가능하면 **L4/A100**(bf16, batch 키움). 0.6B에서 효과 있던 설정을 옮겨서 |

(위 zero-shot 숫자는 gold qrels 확정 **이전**(pooling 재시작 전) 정답으로 채점한 예전 결과라 지금 점수와 비교할 수 없습니다 —
순서만 참고하고, 지금 데이터로 `11. zero-shot 비교표`를 다시 돌려 확인하세요. 예전 결과 json은 `artifacts/evaluation/`에 남아 있지만
그 run CSV는 지워져 다시 채점할 수 없고, Colab 결과를 가져오면 같은 이름 파일은 새 결과로 바뀝니다.)

**모든 모델 공통 — 효과가 클 것으로 보는 순서**
1. **학습 query 늘리기**: 지금 학습 query는 237개뿐(행은 7,270개로 충분하지만 표현이 다양하지 않음). 가맹점 문서로 LLM이 검색어를
   만들게 하는 합성 query가 가장 큰 개선 수단 → 데이터 담당과 상의(학습 데이터를 바꾸는 일이라 모두의 비교 기준이 바뀜).
2. **hard negative**: 학습된 모델이 상위에 올리는 오답을 다시 negative로 쓰기(정답인데 판정이 없는 문서가 섞일 수 있어 GIST와 함께).
3. **하이퍼파라미터**: epoch(1~3), lr, batch(L4/A100에서 64), negative 수.
4. **검색 시스템**: 키워드 검색(BM25)과 섞는 hybrid, 상위 결과를 다시 정렬하는 reranker — 모델 밖 처리라 `NOTE`를 `서비스도 필요:`로.

**점수 읽을 때**: Judged@10이 낮으면(상위 10개 중 판정 없는 문서가 많음) 실제보다 낮게 나옵니다. 절대값보다 **같은 조건에서 기준 대비 Δ**로
판단하고, 서비스 후보는 상위 결과를 사람이 직접 훑어보는 확인도 합니다.

## 12. 막히면

| 증상 | 조치 |
|---|---|
| `ImportError: … torchao …` | 설치 셀(`pip uninstall -y torchao`)이 실행됐는지 확인. 이미 torch를 import한 뒤라면 런타임 > 세션 다시 시작 후 처음부터 |
| `ModuleNotFoundError: ir_measures` | 설치 셀 다시 실행 |
| `Colab 환경 문제: …` (2번 셀) | 메시지대로 패키지 설치. `[경고] 확인된 적 없는 메이저 버전`이면 `SMOKE=True`로 먼저 확인 |
| `No such file … data/…` | Drive `store-search-ai/data/`에 `pack_for_colab.py` 결과를 올렸는지 확인 |
| `train_pairs.jsonl과 meta.json이 맞지 않습니다` | `pack_for_colab.py`로 다시 만들어 `data/`째 다시 올리기 |
| 평가(9번) 중 `CUDA out of memory` | `EVAL_BATCH_SIZE`를 128/64로 |
| `임베딩에 NaN/inf가 있습니다` | `EVAL_DTYPE = "float32"`로 바꾸고 기준 모델 결과 폴더(`runs/model_eval/<기준이름>/`)도 지운 뒤 다시 평가(같은 dtype끼리 비교) |
| `CUDA out of memory` | 런타임 > 세션 다시 시작 후 `HP["mini_batch_size"]`를 절반으로(8, 4B는 2) — 결과는 같고 느려지기만 함, NOTE 불필요. 그래도 안 되면 `HP["batch_size"]` 16 또는 `HP["loss"] = "mnrl"` → `NOTE`에 적기 |
| `loss가 NaN/inf` | 저장된 것 없음. `learning_rate`를 절반으로, 또는 bf16 GPU(L4/A100) |
| `처음 실행과 설정/데이터가 다릅니다` | `RESUME_TAG`로 이어 할 때는 처음 설정 그대로 |
| `처음 실행은 fp16, 지금 GPU는 bf16입니다` | 이어 하기는 처음과 같은 종류의 GPU에서만(T4끼리, L4·A100끼리). 아니면 처음부터 |
| `저장본을 다시 불러오니 임베딩이 다릅니다` | float32로도 안 맞은 경우 — 출력 전체 공유(그 폴더는 `.partial`로 남고 쓰지 않음) |
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
