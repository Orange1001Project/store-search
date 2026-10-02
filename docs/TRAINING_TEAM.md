# 팀 학습 가이드 — 실험은 자유롭게, 결과는 서비스로 이어지게

Arctic(Snowflake)·BGE-M3·Qwen3를 각자 코드와 설정을 바꿔 가며 실험하되, 나중에 **가장 좋았던 모델 폴더 하나와 기록만 보고
검색 서비스·벡터DB에 바로 연결**할 수 있게 하기 위한 최소 규칙입니다. 설계 배경은 `docs/TRAINING.md`에 있습니다.

> **요약**
> - 코드·설정은 마음대로 바꿔도 됩니다. 실험 중 코드는 **Colab 편집기에서 바로** 고치고(다시 올릴 필요 없음), 커밋·push는 좋은 결과가 나온 뒤에 합니다.
> - 사람이 적는 건 **Colab의 `NOTE` 한 줄**과, 나중에 좋은 결과가 나왔을 때 **공유 시트 한 줄**뿐입니다. 나머지는 자동으로 기록됩니다.
> - **학습 → 평가 → 수정 → 다시 학습은 전부 Colab 안에서** 합니다(학습 노트북이 바로 공식 채점까지 함). VS Code에는 실험이 끝난 뒤 결과만 가져와 저장합니다(3-4절).
> - 평가 기준(정답 파일·채점 코드)만은 아무도 바꾸지 않습니다. 반복 평가는 **val**로만, test는 최종 후보를 정한 뒤 한 번만.

---

## 0. Colab 노트북 — 무엇을 열고, 어디를 고치나

Colab에서 실행하는 파일은 전부 **`colab/*.ipynb`** 입니다. 같은 이름의 `.py`는 git·코드 리뷰용 원본이라 Colab에서 열지 않습니다.

| 노트북 | 언제 | 설정 셀에서 바꾸는 것 |
|---|---|---|
| `colab/smoke_test_finetune.ipynb` | **처음 한 번**(또는 Colab 환경이 바뀐 것 같을 때) — 가짜 데이터로 **학습 → 평가 → 리더보드** 전체가 도는지 확인, 마지막에 `통과` | `TARGET`(`"qwen"`/`"arctic"`), 재개 테스트 때만 `RESUME_TAG` |
| `colab/run_finetune_simple.ipynb` | **Arctic / BGE-M3: 학습 + 바로 val 채점 + 리더보드** (full fine-tuning) | `OWNER`, `MODEL_CONFIG`(`arctic_ko.yaml` / `arctic_ko_query.yaml` / `bge_m3.yaml`), `NOTE`, `cfg = FinetuneConfig(...)` 안의 값 |
| `colab/run_finetune_qwen3.ipynb` | **Qwen3: 학습 + 바로 val 채점 + 리더보드** (LoRA) | 위와 같음 + `MODEL_CONFIG`(`qwen3_0_6b.yaml` / `qwen3_0_6b_store.yaml` / `qwen3_4b.yaml` …), 4B면 `BASE_DTYPE`·`BATCH_SIZE`·`LOSS` |
| `colab/run_model_eval_encoding.ipynb` | **여러 모델 한꺼번에 평가** — zero-shot 비교표, 이미 학습한 run 여러 개 재평가. 채점까지 Colab에서 | `MODEL_CONFIG_NAMES`(`None`이면 `configs/models/` 전부), `BASELINE_TAG` |

**여는 법**
- Colab 메뉴 **파일 > 노트북 업로드** → 로컬 저장소의 `colab/*.ipynb` 선택. 또는 같은 메뉴의 **GitHub** 탭에서 저장소·브랜치를
  골라 열기(private 저장소면 GitHub 권한 허용 필요).
- 노트북은 **T4 GPU 런타임**으로 열리게 설정돼 있습니다. 실행 전에 메뉴 **런타임 > 런타임 유형 변경**에서 GPU인지 한 번 확인하세요.
- 노트북을 열기 전에 Drive에 `project` 폴더가 올라가 있어야 합니다(3-1절).

**학습 노트북의 셀 순서** (위에서부터 차례로 실행)

| 셀 | 하는 일 | 고치나? |
|---|---|---|
| 안내 + 설명 | 이 노트북이 무엇을 하는지 | — |
| GPU 확인 | `CUDA: True`, `Tesla T4` 등이 찍히는지 | 아니오 |
| 라이브러리 설치 | 채점용 `ir-measures`·`pytrec-eval-terrier`만 설치(HF 계열은 Colab 기본 버전 그대로 — 다운그레이드 안 함) | 아니오 |
| Drive 연결 | `drive.mount(...)` — 처음엔 권한 허용 창이 뜸 | 아니오 |
| 경로·import | Drive의 `project/src`를 불러옴 + `check_environment()`가 라이브러리 버전 출력·점검 | 아니오 |
| **`## 설정`** | 맨 앞의 `reload_project()`가 Drive의 최신 `src/` 코드를 다시 불러옴 + `OWNER`, `MODEL_CONFIG`, `NOTE`, `RESUME_TAG`, `cfg = FinetuneConfig(...)` | **예 — 여기만**(코드를 고친 뒤에는 **이 셀부터 다시 실행**) |
| **실행** | `final_dir = run_finetune(cfg)` — 학습 → 저장 → 검증 → 기록 | 아니오 |
| `## 평가 (val)` (셀 2개) | 기준 zero-shot 모델(처음 한 번만 자동) + 방금 학습한 모델을 **공식 evaluator로 채점**, 기준 대비 Δ·p-value 출력 | 학습 없이 기존 run만 평가할 때 `EVAL_RUN_TAG`만 |
| `## 리더보드 (val)` | Drive에 쌓인 모든 평가를 nDCG@10 순으로 | 아니오 |
| `## (평가 후) 좋은 run을 KEEP으로 남기기` | 남길 run 표시 한 줄(주석 처리돼 있음) | 필요할 때 주석을 풀고 TAG만 바꿔 실행(7절) |
| `## (최종 후보 확정 후 한 번만) test 평가` | test 채점 — 기본값 `FINAL_TEST = False`로 꺼져 있음 | 팀이 최종 후보를 정한 뒤에만 `True` |

**지킬 것**
- 노트북에서 바꾸는 건 **설정 셀의 값뿐**입니다. 로직(학습 방식·데이터 처리)은 Drive의 `src/` 파일에서 고칩니다(3-2절) —
  노트북 셀 안에 쓴 로직은 기록(`code_snapshot.zip`)에 남지 않습니다.
- 노트북 구조 자체를 바꿔 팀과 공유하고 싶으면 `.ipynb`를 직접 고치지 말고 `colab/*.py`를 고친 뒤
  `python scripts/build_colab_notebooks.py`로 다시 생성해서 둘 다 커밋합니다(어긋나면 `tests/test_colab_notebooks.py`가 실패).

---

## 1. 기록은 딱 세 군데

| 어디 | 누가 | 언제 | 무엇을 |
|---|---|---|---|
| **`model_manifest.json`** (모델 폴더 안) | **자동** | 학습이 끝날 때마다 | 모든 설정값, 학습 데이터 해시, 코드 버전(git 커밋) + **학습에 쓴 코드 사본**(`code_snapshot.zip`), GPU·라이브러리 버전, 서비스가 따라야 할 값 — **손대지 않습니다** |
| **Colab 설정 셀의 `NOTE`** | 나 | 기본값에서 무언가 바꿨을 때 | 무엇을 왜 바꿨는지 한 줄(4절) |
| **공유 시트** | 나 | **2단계부터, 남길 run만** | run 하나당 한 줄(8절) |

아래는 **기록하는 곳이 아니라 "설정"**입니다. 실험할 때 바꾸는 값이고, 바꾼 값은 manifest에 자동으로 남습니다.

| 이름 | 무엇 | 언제 바꾸나 |
|---|---|---|
| `OWNER` | 내 이름(영문 소문자) — run 이름에 들어감 | 처음 한 번 |
| `MODEL_CONFIG` | 베이스 모델 선택(`arctic_ko.yaml` / `bge_m3.yaml` / `qwen3_0_6b.yaml` 등, 0절 표) | 모델 바꿀 때 |
| `batch_size`, `learning_rate`, `loss` … | 학습 설정 | 실험할 때 |
| `RESUME_TAG` | 끊긴 학습을 이어 할 때만 | Colab 연결이 끊겼을 때(9절) |
| `configs/models/*.yaml` | 모델별 기본 설정(query prompt 등) | 팀 합의 후에만 |
| `QUERY_PROMPT_OVERRIDE` | Qwen3 노트북 전용 prompt 설정(보통은 `qwen3_*_store.yaml`처럼 yaml로 고르는 게 낫다) | Arctic/BGE는 해당 없음 |

**`KEEP`**도 기록이 아닙니다. "이 run은 지우지 마" 표시일 뿐입니다(7절).

---

## 2. 단계: 처음엔 기록 없이 돌려보고, 비교할 수 있게 되면 기록

| | 1단계 — 돌려보기 | 2단계 — 비교·기록 |
|---|---|---|
| 언제 | val 정답(qrels) 배포 전 | 데이터 담당이 val 정답을 배포한 뒤 — **2026-10-02 val/test gold 확정, 지금은 2단계** |
| 목적 | 학습이 끝까지 도는지, 시간·메모리, 어떤 설정이 T4에 맞는지 파악 | 점수로 비교해서 서비스 후보를 고름 |
| 평가 | 불가(정답이 아직 없음) | 학습 노트북에서 바로 val 채점(10절) |
| 기록 | manifest(자동)만. `NOTE`는 적으면 좋음 | 남길 run만 **공유 시트 + KEEP** |
| 코드 | 커밋 안 해도 됨 | 시트에 올릴 run의 코드는 **그때 커밋·push**(시트에 커밋 번호 적음) |

1단계에 학습한 모델도 manifest가 자동으로 남기 때문에, 2단계가 되면 그 모델을 평가해서 시트에 올려도 됩니다.
단, Drive는 내 run을 최신 3개만 남기므로 남기고 싶은 1단계 run이 있으면 KEEP 해 두세요.

---

## 3. 작업 순서

```
[처음 한 번]      VS Code: git pull → pack_for_colab.py → Drive에 project 업로드          (3-1)
[반복 — Colab만]  설정·코드 수정 → 학습 셀 → 평가 셀(val 공식 채점, 기준 대비 Δ·p) → 리더보드 확인
                  → 좋으면 KEEP, 아니면 설정·코드 고쳐서 학습 셀부터 다시                     (3-2, 10)
[마지막 한 번]    Drive의 store-search-ai 폴더 내려받기 → import_colab_results.py --verify
                  → 저장소에 결과·KEEP 모델 정리 → 커밋                                      (3-3, 3-4)
```

올리는 건 **처음 한 번(또는 git에서 새 코드를 받았을 때)** 만 하고, 실험하면서 코드를 고치고 점수를 보는 건 **전부 Colab에서** 합니다.

### 3-1. 처음 한 번: VS Code → Drive

```
[VS Code]  git pull (또는 코드·설정 수정 — 커밋 안 해도 됨)
    ↓      터미널에서:  python scripts/pack_for_colab.py
[로컬]     colab_upload/project/ 폴더가 생김 (코드 + 설정 + 학습 데이터 + 평가용 corpus·queries·정답 + git 커밋 정보)
    ↓
[Drive]    내 드라이브/store-search-ai/ 의 기존 project 폴더를 지우고, 새 project 폴더를 업로드
    ↓
[Colab]    학습 노트북 열기 (Arctic/BGE: run_finetune_simple.ipynb, Qwen3: run_finetune_qwen3.ipynb)
           → 설정 셀에 OWNER, MODEL_CONFIG, NOTE 적고 위에서부터 실행 (0절) → 학습 후 바로 val 채점·리더보드
    ↓
[Drive]    runs/finetune/<TAG>/   모델 + model_manifest.json (평가 결과도 manifest에 기록)
           runs/model_eval/<tag>/ run.csv,  runs/evaluation/  지표 json
```

- **push는 학습에 필요 없습니다.** `pack_for_colab.py`가 "어느 커밋에서, 어떤 파일을 커밋 안 한 채로 올렸는지"를 자동으로
  적고(`code_version.json`), 학습할 때 **실제로 쓴 코드 사본이 모델 폴더에 함께 저장**됩니다. 그래서 커밋을 안 했어도
  나중에 그 모델이 어떤 코드로 학습됐는지 그대로 확인할 수 있습니다.
- 처음 한 번은 `colab/smoke_test_finetune.ipynb`(가짜 데이터, 몇 분)로 마지막에 `통과`가 나오는지 확인하세요.

- 노트북 여는 법과 셀 순서는 0절.

### 3-2. 실험 중: Colab에서 바로 코드 고치기 (다시 올릴 필요 없음)

1. Colab 왼쪽 **파일 아이콘(📁)** → `drive/MyDrive/store-search-ai/project/src/store_search_ai/training/st_finetune.py`
   (또는 고칠 파일)을 **더블클릭** → 오른쪽에 편집기가 열립니다. 고치면 Drive 파일에 바로 저장됩니다.
2. 학습 노트북의 **설정 셀부터 다시 실행**합니다(이어서 실행·평가 셀까지 돌리면 점수가 바로 나옴). 설정 셀 맨 앞의
   `reload_project()`가 고친 코드를 다시 불러옵니다(세션 재시작 불필요). 평가 코드만 고쳤으면 평가 셀부터 다시 실행해도 됩니다(평가 셀에도
   같은 줄이 있음). 이상하게 예전 코드가 도는 것 같으면 그때만 **런타임 > 세션 다시 시작**.
   (IPython `%autoreload`는 쓰지 않습니다 — Colab이 Python 3.13 + IPython 7.34라 `No module named 'imp'` 오류가 납니다.)
3. 기록은 자동입니다: 학습할 때 그 순간의 코드가 모델 폴더의 `code_snapshot.zip`에 저장되고, manifest의
   `code.edited_after_pack`이 `true`로 남습니다(올린 뒤 Colab에서 고쳤다는 표시). **`NOTE`에 무엇을 고쳤는지 한 줄**은 적어 주세요.

**주의 — 고친 코드는 Drive에만 있습니다.**
- 3-1을 다시 하면(기존 `project` 폴더 삭제 후 업로드) **Colab에서 고친 내용이 사라집니다.** 다시 올리기 전에 3-3으로 먼저 가져오세요.
- 로컬 VS Code와 Drive 양쪽에서 같은 파일을 동시에 고치지 마세요. 실험 중에는 Drive(Colab) 쪽만 고칩니다.

### 3-3. 좋은 결과가 나왔을 때: 그 코드를 git으로 가져오기

그 run 폴더의 `code_snapshot.zip`이 **학습에 쓴 코드 그대로**입니다. 이걸 로컬에 풀어서 커밋합니다.

1. Drive `runs/finetune/<TAG>/code_snapshot.zip`을 내려받습니다.
2. 로컬 저장소 루트에서 `src/`에 덮어써 풉니다(PowerShell):
   ```powershell
   Expand-Archive -Force code_snapshot.zip src/
   ```
3. `git diff`로 바뀐 내용을 확인한 뒤, 개인 실험 브랜치(예: `exp/jisu-bge-negmining`)에 커밋·push합니다.
4. 공유 시트의 "코드커밋" 칸에 그 커밋 번호를 적습니다.

### 3-4. 실험이 다 끝나면: 결과를 VS Code로 가져와 저장

1. 웹 Google Drive에서 `내 드라이브/store-search-ai` 폴더를 **다운로드** → 압축 해제(예: `C:/Users/me/Downloads/store-search-ai`).
   `project/`는 필요 없으니 `runs/`만 받아도 됩니다.
2. 로컬 저장소 루트에서:
   ```bash
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --dry-run   # 무엇을 옮길지 확인
   python scripts/import_colab_results.py --drive-dir "C:/Users/me/Downloads/store-search-ai" --verify
   ```
   - `runs/model_eval/` → `results/model_eval/`, `runs/evaluation/` → `artifacts/evaluation/storesearch_ko_v1/`
     (smoke test 같은 **비공식 평가는 자동으로 빠짐**)
   - **KEEP 표시한 run**만 `models/<TAG>/` + `configs/models/<TAG>.yaml`로 복사(특정 run만: `--models <TAG> ...`)
   - `--verify`: 가져온 평가마다 로컬 공식 evaluator로 **다시 채점**해 Colab 점수와 같은지 확인(다르면 종료코드 1 — 정답 파일 버전이 다른 것)
3. `git add results/ artifacts/ configs/models/` 후 커밋(`models/`는 용량 때문에 .gitignore — 서비스 후보 모델은 팀 공유 스토리지에 따로 보관).

---

## 4. `NOTE`에 쓰는 것

학습 노트북 설정 셀의 `NOTE = ""`에 **기본값에서 바꾼 것을 한 줄로** 적습니다. 바꾼 값 자체는 자동 기록되지만,
**왜 바꿨는지**는 사람만 알기 때문입니다.

```python
NOTE = "negative 3→5개, BGE에서 어려운 negative가 더 효과 있는지"
NOTE = "GIST 대신 MNRL (T4 메모리 부족)"
```

**가장 중요한 경우 — 모델 밖에서 하는 처리를 추가했을 때.** 서비스는 모델 폴더만 불러와서 쓰기 때문에, 모델 폴더에 저장되지
않는 처리는 서비스에서도 **똑같이 다시 해줘야** 같은 성능이 나옵니다. 이런 처리를 넣었다면 `NOTE`를 **`서비스도 필요:`로 시작**해서
어떤 파일의 어떤 함수인지 적습니다.

```python
NOTE = "서비스도 필요: 쿼리 특수문자 제거 (store_search_ai/data/text_cleaning.py 에 새로 만든 strip_query_symbols)"
```

| 이런 걸 바꿨다면 | 자동으로 기록되나? | 할 일 |
|---|---|---|
| 하이퍼파라미터, loss | 예 | `NOTE`에 이유 |
| 학습 코드 수정 | 예(코드 사본 + 커밋 정보) | `NOTE`에 무엇을 고쳤는지 |
| 학습 데이터 가공(negative 추출 방식 등) | 예(데이터 해시) | `NOTE` + jsonl과 meta.json을 **같이** 다시 만들어 올리기 |
| 문서 텍스트 template(T2 등) | 예(`serving.document_template`) | 평가도 같은 template으로(평가 노트북 `TEMPLATE`, 또는 `evaluate_model(template=...)`) |
| **쿼리/문서 전처리 추가** | **아니오** | **`NOTE`에 `서비스도 필요:` + 파일·함수 이름** |
| **BM25 hybrid, reranker 등 후처리** | **아니오** | **`NOTE`에 `서비스도 필요:`** + 평가 run 이름에 표시 |

---

## 5. 절대 바꾸지 않는 것 — 평가 기준

누구 모델이 좋은지 비교하려면 모두 같은 기준으로 재야 합니다. 아래는 **아무도 고치지 않습니다.**

- 정답: 데이터 담당이 배포한 val qrels, `queries.csv`, corpus
- 채점 코드: `scripts/13_evaluate_run.py`, `14_run_model_eval.py`, `15_score_model_runs.py`, `src/store_search_ai/evaluation/`
- **test split은 보지 않습니다.** 모든 선택은 val로 하고, test는 팀이 최종 후보를 정한 뒤 한 번만 봅니다.

채점 방식을 바꿔야 한다면 팀에서 합의한 뒤 **모든 run을 다시 채점**합니다.

## 6. 결과 폴더가 서비스에 쓸 수 있는 상태인지

서비스는 `SentenceTransformer(모델폴더)` 한 줄로 모델을 불러옵니다. **평가(10절)가 정상적으로 됐다면 이 조건은 이미 충족**된 것입니다
— 평가도 같은 방식으로 불러오기 때문입니다. 기본 학습 코드는 이 형식으로 저장하고, 저장 직후 다시 불러와서 검증까지 합니다.

- 다른 라이브러리(FlagEmbedding 등)로 학습했다면 최종 모델을 sentence-transformers 형식으로 저장하고, manifest도 남겨야 합니다
  (`store_search_ai.pipeline.common.write_model_manifest`) — 이 경우는 시작 전에 팀에 공유해 주세요.
- BGE-M3의 sparse/multi-vector처럼 **벡터 하나로 표현되지 않는 방식**은 벡터DB 구조 자체가 달라지므로 역시 시작 전에 공유합니다.

## 7. KEEP — 지우면 안 되는 run 표시

Drive는 학습이 끝날 때마다 **내 run 중 같은 베이스 모델의 최신 3개만 남기고 오래된 것은 자동 삭제**합니다
(다른 사람 run은 건드리지 않음). 남겨야 하는 run은 그 폴더 안에 **`KEEP`이라는 이름의 빈 파일**을 만들면 삭제되지 않습니다.
Drive 화면에서는 빈 파일을 만들 수 없으니 Colab에서 이 한 줄을 실행합니다(학습 노트북 맨 아래 `## (평가 후) 좋은 run을 KEEP으로 남기기` 셀에 주석으로 들어 있음 — 주석을 풀고 TAG만 바꿔 실행):

```python
(DRIVE_ROOT / "runs" / "finetune" / "bge_m3_ft_jisu_20260930_0512" / "KEEP").touch()
```

**KEEP은 자동으로 생기지 않습니다 — 직접 표시합니다.** KEEP 하는 기준:

1. 모델별 **baseline run**(기본값으로 학습한 것) — 다른 실험의 비교 기준이라 지워지면 안 됩니다.
2. **공유 시트에 올린 run** — 시트에 적었는데 모델이 지워지면 나중에 쓸 수 없습니다.
3. **서비스 후보·발표에 쓸 run**

그 외(이것저것 바꿔 본 run)는 KEEP 하지 않고 자동 정리에 맡깁니다.

## 8. 공유 시트 (2단계, 남길 run만 한 줄)

**만드는 법**: 팀 공유 Google Drive 폴더에 Google Sheets를 하나 만들고(한 명이 만들어 링크 공유), 첫 줄에 아래를
그대로 붙여넣습니다(탭으로 구분돼 있어 칸이 자동으로 나뉨). run 하나당 한 줄씩 아래로 추가합니다.

```
TAG	이름	베이스모델	NOTE	코드커밋	학습데이터해시	GPU	precision	nDCG@10	Judged@10	Recall@100	zero-shot대비	p-value	KEEP
```

| 칸 | 어디서 복사하나 |
|---|---|
| TAG | run 폴더 이름 |
| 이름 / 베이스 모델 | TAG 안에 있음 |
| NOTE | manifest `hyperparameters.note` |
| 코드 커밋 | 시트에 올리면서 커밋·push한 번호(`git log -1 --format=%h`). 기본 코드면 "기본" |
| 학습 데이터 해시 앞 8자리 | manifest `training_data.sha256` |
| GPU / precision | manifest `environment.gpu` / `precision` |
| val nDCG@10, Judged@10, Recall@100 | 학습 노트북 "평가" 셀 출력(또는 리더보드 셀) |
| zero-shot 대비 차이, p-value | 리더보드의 `ΔnDCG@10` / `p(nDCG@10)` |

**숫자 읽는 법**
- val은 136개 쿼리라 nDCG@10에 ±0.05 정도 오차가 있습니다. **차이가 0.03보다 작으면 p-value 없이 "좋아졌다"고 하지 않습니다.**
- **Judged@10**(상위 10개 중 정답 판정이 있는 비율)이 낮으면 점수가 실제보다 낮게 나왔을 수 있습니다. 지금 정답은 키워드
  검색 결과로만 만들어서, 모델이 새로 찾아낸 문서는 판정이 없어 오답으로 계산되기 때문입니다.
- **같은 학습 데이터 해시 + 같은 precision**(T4=fp16, L4/A100=bf16) **+ 같은 라이브러리 버전**(리더보드 `libs` 칸)인 run끼리 비교합니다.
  Colab은 기본 패키지를 자주 올리므로, 버전이 바뀌었으면 기준 zero-shot 모델도 그 버전으로 다시 평가해서 비교합니다.

## 9. 자주 막히는 것

| 증상 | 조치 |
|---|---|
| `CUDA out of memory` | `batch_size=16` 또는 `loss="mnrl"`, `NOTE`에 적기 |
| `loss가 NaN/inf`로 중단 | 저장된 것 없음. `learning_rate`를 절반으로, 또는 L4/A100 런타임 |
| Colab 연결이 끊김 | 로그에 `[체크포인트] … 저장 완료`가 나온 뒤였다면 `RESUME_TAG = "<TAG>"`를 넣고 **다른 설정은 그대로** 다시 실행. 그 전이면 처음부터 |
| `처음 실행과 설정/데이터가 다릅니다` | 이어서 학습하려면 메시지에 나온 값을 처음 값으로 되돌리기 |
| `sha256이 meta.json과 다릅니다` 경고 | 학습 데이터 두 파일을 같이 다시 올리기(`pack_for_colab.py`를 쓰면 자동으로 같이 들어감) |
| Drive 용량 부족 | 휴지통 비우기. Arctic/BGE는 학습 중 체크포인트로 약 7GB가 잠깐 필요 → 부족하면 `SAVE_MID_CHECKPOINT = False` |
| 평가 셀에서 `No such file ... qrels_val.trec` / corpus 없음 | `--no-eval-data` 없이 `pack_for_colab.py`로 다시 올리기 |
| 평가 셀 `ModuleNotFoundError: ir_measures` | 설치 셀을 다시 실행(세션을 새로 열면 설치부터 다시) |
| 평가가 오래 걸림 | 문서 21만 개를 인코딩하는 정상 시간(모델당 수 분~수십 분). 기준 zero-shot 모델은 처음 한 번만 평가되고 그다음부터는 건너뜀 |
| `test split은 최종 후보를 정한 뒤 한 번만` 에러 | 정상 — 반복 실험은 val로. 최종 평가 때만 `FINAL_TEST = True`(학습 노트북) 또는 `ALLOW_TEST = True`(평가 노트북) |

## 10. 평가 — Colab 안에서 바로 (2단계)

채점은 로컬 `scripts/13_evaluate_run.py`와 **같은 공식 evaluator 함수**로 Colab에서 합니다. 그래서 Colab에서 본 점수가 그대로
공식 점수입니다(마지막에 `import_colab_results.py --verify`가 로컬에서 다시 채점해 같은지 확인).

**학습한 모델 평가 — 학습 노트북의 `## 평가 (val)` 셀** (학습 셀 다음에 이어서 실행)
1. 비교 기준인 **zero-shot 베이스 모델**(`MODEL_CONFIG`의 원래 모델)이 아직 평가 안 됐으면 먼저 자동으로 평가합니다(처음 한 번만).
2. 방금 학습한 모델을 val로 채점하고 지표·95% 신뢰구간·**기준 대비 Δ와 p-value**를 출력합니다.
3. 학습 없이 이미 있는 run을 다시 평가하려면 학습 셀은 건너뛰고 `EVAL_RUN_TAG = "<TAG>"`를 넣고 평가 셀만 실행합니다.
4. 결과는 모델 폴더의 `model_manifest.json` `evaluations`에도 자동으로 기록됩니다.

**전체 비교 — `## 리더보드 (val)` 셀**: Drive에 쌓인 모든 평가(팀원 것 포함, 같은 Drive를 쓸 때)를 nDCG@10 순으로 보여 줍니다.

**zero-shot 비교표·여러 run 재평가 — `colab/run_model_eval_encoding.ipynb`**: `MODEL_CONFIG_NAMES`로 고른 모델(또는 전부)을 한 번에
평가하고 리더보드까지 냅니다. prompt만 다른 변형(`arctic_ko_query`, `qwen3_*_store`)은 문서 임베딩을 재사용해 빠릅니다.

**최종 test 평가** — 팀이 최종 후보를 정한 뒤 **한 번만**: 학습 노트북 맨 아래 셀에서 `FINAL_TEST = True`, 또는 평가 노트북에서
`SPLIT = "test"`, `ALLOW_TEST = True`. 그 외에는 test 채점이 코드에서 막혀 있습니다.

**결과 파일** (Colab에서는 Drive `store-search-ai/runs/` 밑, 가져온 뒤에는 저장소 안)

| Drive (Colab) | 로컬로 가져온 뒤 | 내용 |
|---|---|---|
| `runs/model_eval/<tag>/run_t1_minimal_val.csv` | `results/model_eval/<tag>/` | 검색 결과: 쿼리마다 상위 100개 문서 |
| `runs/evaluation/<tag>_t1_minimal_val_evaluation.json` | `artifacts/evaluation/storesearch_ko_v1/` | `aggregate`(지표) + `query_bootstrap_ci95` + `comparison`(기준 대비) — **시트에 적는 숫자** |
| `runs/evaluation/<tag>_t1_minimal_val_per_query.csv` | 위와 같은 폴더 | 쿼리별 지표(어떤 쿼리가 좋아지고 나빠졌는지) |
| `runs/finetune/<TAG>/model_manifest.json` | `models/<TAG>/` (KEEP한 run) | 학습 기록 + `evaluations` |

**로컬에서 평가하는 방법도 그대로 있습니다**(로컬 GPU가 있을 때): `python scripts/14_run_model_eval.py --model-config configs/models/<TAG>.yaml --split val`
→ `python scripts/15_score_model_runs.py --split val`. 같은 evaluator라 결과가 같습니다.

---

## 11. 자주 묻는 질문

**Q. Colab "설정 셀"이 어디예요?**
학습 노트북(`colab/run_finetune_simple.ipynb`, `colab/run_finetune_qwen3.ipynb`)의 **"## 설정"** 제목 바로 아래 코드 셀
(`OWNER = ""`부터 `cfg = FinetuneConfig(...)`까지)입니다. 셀 전체 순서는 0절 표.
그 다음 셀(`final_dir = run_finetune(cfg)`)이 학습 실행 셀이라, 코드를 고친 뒤 다시 돌릴 때는 이 셀만 다시 실행하면 됩니다.

**Q. 학습 노트북을 계속 고치면 되나요?**
**설정값만** 노트북 설정 셀에서 바꿉니다. 로직은 Drive의 `src/` 파일을 **Colab 편집기에서 바로** 고칩니다(3-2절 —
다시 올릴 필요 없음).

| 바꾸려는 것 | 어디를 고치나 |
|---|---|
| epoch, batch, lr, loss, negative 개수 등 | 노트북 설정 셀의 `cfg = FinetuneConfig(...)` 안의 값 |
| 학습 방식(새 loss, 학습 루프, 저장 방식) | Drive `project/src/store_search_ai/training/st_finetune.py` |
| 학습 데이터를 행으로 펼치는 방식 | Drive `project/src/store_search_ai/training/finetune.py` |
| positive/negative 뽑는 방식 | `src/store_search_ai/data/finetune_dataset.py` (학습 데이터를 다시 만드는 일이라 데이터 담당과 상의) |

**노트북 셀 안에 로직 코드를 직접 쓰면 기록에 안 남습니다.** 자동 저장되는 코드 사본은 `src/store_search_ai`만 담기 때문입니다.
셀 안에서 잠깐 시험해 보는 건 괜찮지만, 결과를 남길 학습은 그 로직을 Drive의 `src/` 파일로 옮긴 뒤 돌리세요.

**Q. 공유 시트는 어디에 있나요?**
처음에 한 명이 팀 공유 Drive에 만듭니다(8절의 헤더를 첫 줄에 붙여넣기). 기록은 2단계(val 정답 배포 후)부터 합니다.

**Q. KEEP은 자동인가요?**
아니요, 직접 표시합니다. 학습 노트북 맨 아래 `## (평가 후) 좋은 run을 KEEP으로 남기기` 셀의 주석을 풀고 TAG를 바꿔 실행하면 그 run 폴더에 빈 `KEEP` 파일이 생깁니다.
기준은 7절(baseline / 시트에 올린 run / 서비스 후보·발표용).

**Q. 평가하려면 파일을 VS Code로 옮겨야 하나요?**
아니요. 학습 노트북의 평가 셀이 Colab에서 바로 공식 채점까지 합니다(10절). 파일을 옮기는 건 실험이 다 끝난 뒤
`import_colab_results.py`로 한 번뿐입니다(3-4절).

**Q. Colab 점수를 믿어도 되나요?**
로컬 13번과 같은 evaluator 함수로 채점합니다. 가져올 때 `--verify`가 로컬에서 다시 채점해 같은지 확인하고, 다르면 실패로 알려 줍니다.

**Q. `.py`랑 `.ipynb`가 둘 다 있는데 뭘 열어요?**
Colab에서는 항상 `.ipynb`를 엽니다. `.py`는 git에서 코드 리뷰·diff를 보기 위한 원본이고, `.ipynb`는 그걸로 자동 생성됩니다(0절 "지킬 것").

---

## 부록. 데이터 담당 — 학습 데이터·정답 배포

1. train 애노테이션 반영(`docs/PIPELINE.md` 4절) → `python scripts/prepare_finetune_dataset.py`
2. `data/finetune/train_pairs.jsonl`과 `train_pairs.meta.json`을 **같이** 커밋·push
3. 공지: 커밋 번호, `train_pairs_sha256` 앞 8자리, qrels 종류(provisional/final)
4. 데이터를 다시 만들면 새 커밋으로 다시 공지(다른 데이터로 학습한 run끼리는 비교하지 않음)
5. val 조정이 끝나면 최종 qrels를 push·공지 → **2단계 시작**
