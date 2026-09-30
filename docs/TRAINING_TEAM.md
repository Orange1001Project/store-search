# 팀 학습 가이드 — 실험은 자유롭게, 결과는 서비스로 이어지게

Arctic(Snowflake)·BGE-M3를 각자 코드와 설정을 바꿔 가며 실험하되, 나중에 **가장 좋았던 모델 폴더 하나와 기록만 보고
검색 서비스·벡터DB에 바로 연결**할 수 있게 하기 위한 최소 규칙입니다. 설계 배경은 `docs/TRAINING.md`에 있습니다.

> **요약**
> - 코드·설정은 마음대로 바꿔도 됩니다. 커밋·push도 학습 전에 안 해도 됩니다.
> - 사람이 적는 건 **Colab의 `NOTE` 한 줄**과, 나중에 좋은 결과가 나왔을 때 **공유 시트 한 줄**뿐입니다. 나머지는 자동으로 기록됩니다.
> - 평가 기준(정답 파일·채점 코드)만은 아무도 바꾸지 않습니다.

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
| `MODEL_CONFIG` | 베이스 모델 선택(`arctic_ko.yaml` / `bge_m3.yaml`) | 모델 바꿀 때 |
| `batch_size`, `learning_rate`, `loss` … | 학습 설정 | 실험할 때 |
| `RESUME_TAG` | 끊긴 학습을 이어 할 때만 | Colab 연결이 끊겼을 때(9절) |
| `configs/models/*.yaml` | 모델별 기본 설정(query prompt 등) | 팀 합의 후에만 |
| `QUERY_PROMPT_OVERRIDE` | Qwen3 전용 prompt 설정 | Arctic/BGE는 해당 없음 |

**`KEEP`**도 기록이 아닙니다. "이 run은 지우지 마" 표시일 뿐입니다(7절).

---

## 2. 단계: 처음엔 기록 없이 돌려보고, 비교할 수 있게 되면 기록

| | 1단계 — 돌려보기 | 2단계 — 비교·기록 |
|---|---|---|
| 언제 | 지금 ~ **val 정답(qrels) 배포 전** | 데이터 담당이 val 정답을 배포한 뒤 |
| 목적 | 학습이 끝까지 도는지, 시간·메모리, 어떤 설정이 T4에 맞는지 파악 | 점수로 비교해서 서비스 후보를 고름 |
| 평가 | 불가(정답이 아직 없음) | 공식 채점으로 val 평가(10절) |
| 기록 | manifest(자동)만. `NOTE`는 적으면 좋음 | 남길 run만 **공유 시트 + KEEP** |
| 코드 | 커밋 안 해도 됨 | 시트에 올릴 run의 코드는 **그때 커밋·push**(시트에 커밋 번호 적음) |

1단계에 학습한 모델도 manifest가 자동으로 남기 때문에, 2단계가 되면 그 모델을 평가해서 시트에 올려도 됩니다.
단, Drive는 내 run을 최신 3개만 남기므로 남기고 싶은 1단계 run이 있으면 KEEP 해 두세요.

---

## 3. 매번 하는 순서 (VS Code → Drive → Colab)

```
[VS Code]  코드·설정 수정 (커밋 안 해도 됨)
    ↓      터미널에서:  python scripts/pack_for_colab.py
[로컬]     colab_upload/project/ 폴더가 생김 (코드 + 모델 설정 + 학습 데이터 + git 커밋 정보)
    ↓
[Drive]    내 드라이브/store-search-ai/ 의 기존 project 폴더를 지우고, 새 project 폴더를 업로드
    ↓
[Colab]    colab/run_finetune_simple.py 를 셀에 붙여넣기 → OWNER, MODEL_CONFIG, NOTE 적고 실행
    ↓
[Drive]    runs/finetune/<TAG>/ 에 모델 + model_manifest.json 저장됨
```

- **push는 학습에 필요 없습니다.** `pack_for_colab.py`가 "어느 커밋에서, 어떤 파일을 커밋 안 한 채로 올렸는지"를 자동으로
  적고(`code_version.json`), 학습할 때 **실제로 쓴 코드 사본이 모델 폴더에 함께 저장**됩니다. 그래서 커밋을 안 했어도
  나중에 그 모델이 어떤 코드로 학습됐는지 그대로 확인할 수 있습니다.
- Colab을 **이미 쓰던 세션**에서 코드를 새로 올렸다면 **런타임 > 세션 다시 시작** 후 실행하세요(예전 코드가 메모리에 남아 있음).
- 처음 한 번은 `colab/smoke_test_finetune.py`(가짜 데이터, 몇 분)로 마지막에 `통과`가 나오는지 확인하세요.

---

## 4. `NOTE`에 쓰는 것

Colab 설정 셀 맨 위의 `NOTE = ""`에 **기본값에서 바꾼 것을 한 줄로** 적습니다. 바꾼 값 자체는 자동 기록되지만,
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
| 문서 텍스트 template(T2 등) | 예(`serving.document_template`) | 평가도 같은 template으로(`14_run_model_eval.py --template`) |
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
Drive 화면에서는 빈 파일을 만들 수 없으니 Colab에서 이 한 줄을 실행합니다(학습 스크립트 맨 아래에도 있음):

```python
(DRIVE_ROOT / "runs" / "finetune" / "bge_m3_ft_jisu_20260930_0512" / "KEEP").touch()
```

KEEP 할 run: 공유 시트에 올린 run, 서비스 후보, 발표에 쓸 run.

## 8. 공유 시트 (2단계, 남길 run만 한 줄)

| 칸 | 어디서 복사하나 |
|---|---|
| TAG | run 폴더 이름 |
| 이름 / 베이스 모델 | TAG 안에 있음 |
| NOTE | manifest `hyperparameters.note` |
| 코드 커밋 | 시트에 올리면서 커밋·push한 번호(`git log -1 --format=%h`). 기본 코드면 "기본" |
| 학습 데이터 해시 앞 8자리 | manifest `training_data.sha256` |
| GPU / precision | manifest `environment.gpu` / `precision` |
| val nDCG@10, Judged@10, Recall@100 | 평가 결과 json(10절) |
| zero-shot 대비 차이, p-value | 10절 `--compare-run` 결과 |

**숫자 읽는 법**
- val은 136개 쿼리라 nDCG@10에 ±0.05 정도 오차가 있습니다. **차이가 0.03보다 작으면 p-value 없이 "좋아졌다"고 하지 않습니다.**
- **Judged@10**(상위 10개 중 정답 판정이 있는 비율)이 낮으면 점수가 실제보다 낮게 나왔을 수 있습니다. 지금 정답은 키워드
  검색 결과로만 만들어서, 모델이 새로 찾아낸 문서는 판정이 없어 오답으로 계산되기 때문입니다.
- **같은 학습 데이터 해시 + 같은 precision**(T4=fp16, L4/A100=bf16)인 run끼리 비교합니다.

## 9. 자주 막히는 것

| 증상 | 조치 |
|---|---|
| `CUDA out of memory` | `batch_size=16` 또는 `loss="mnrl"`, `NOTE`에 적기 |
| `loss가 NaN/inf`로 중단 | 저장된 것 없음. `learning_rate`를 절반으로, 또는 L4/A100 런타임 |
| Colab 연결이 끊김 | 로그에 `[체크포인트] … 저장 완료`가 나온 뒤였다면 `RESUME_TAG = "<TAG>"`를 넣고 **다른 설정은 그대로** 다시 실행. 그 전이면 처음부터 |
| `처음 실행과 설정/데이터가 다릅니다` | 이어서 학습하려면 메시지에 나온 값을 처음 값으로 되돌리기 |
| `sha256이 meta.json과 다릅니다` 경고 | 학습 데이터 두 파일을 같이 다시 올리기(`pack_for_colab.py`를 쓰면 자동으로 같이 들어감) |
| Drive 용량 부족 | 휴지통 비우기. Arctic/BGE는 학습 중 체크포인트로 약 7GB가 잠깐 필요 → 부족하면 `SAVE_MID_CHECKPOINT = False` |

## 10. 평가 (2단계)

- **로컬에 GPU가 있을 때**
  1. Drive `runs/finetune/<TAG>/`를 로컬 `models/<TAG>/`로 내려받습니다.
  2. 그 안의 `eval_config.yaml`을 `configs/models/<TAG>.yaml`로 복사합니다.
  3. `python scripts/14_run_model_eval.py --model-config configs/models/<TAG>.yaml --split val`을 실행합니다.
     결과는 `artifacts/evaluation/storesearch_ko_v1/<TAG>_val_evaluation.json`에 저장되고, manifest에도 자동으로 추가됩니다.
- **GPU가 없을 때**
  1. Drive `runs/finetune/<TAG>/eval_config.yaml`을 로컬 `configs/models/<TAG>.yaml`로 복사합니다(모델 자체는 안 받아도 됨).
  2. `python scripts/pack_for_colab.py --with-eval-data`로 올립니다(corpus 포함).
  3. `colab/run_model_eval_encoding.py`에서 `MODEL_CONFIG_NAMES = ["<TAG>.yaml"]`로 지정하고 실행합니다
     (`model_id: models/<TAG>`는 Drive의 `runs/finetune/<TAG>`로 자동으로 바뀌어 읽힙니다).
  4. Drive `runs/model_eval/<TAG>/`를 로컬 `results/model_eval/<TAG>/`로 받아 `python scripts/15_score_model_runs.py --split val`로 채점합니다.
     이 경로는 manifest에 평가가 자동으로 안 쌓이므로 **공유 시트가 유일한 기록**입니다.
- **zero-shot 대비 p-value**
  ```
  python scripts/13_evaluate_run.py --qrels benchmark/storesearch_ko_v1/qrels_val.trec \
      --run results/model_eval/<TAG>/run_t1_minimal_val.csv --tag <TAG>_val \
      --compare-run results/model_eval/<베이스모델>/run_t1_minimal_val.csv
  ```
  `<베이스모델>`은 yaml의 `name`입니다(`bge_m3`, `snowflake_arctic_embed_l_v2_ko`). zero-shot run도
  **같은 val 정답으로 다시 채점한 것**을 씁니다.

---

## 부록. 데이터 담당 — 학습 데이터·정답 배포

1. train 애노테이션 반영(`docs/PIPELINE.md` 4절) → `python scripts/prepare_finetune_dataset.py`
2. `data/finetune/train_pairs.jsonl`과 `train_pairs.meta.json`을 **같이** 커밋·push
3. 공지: 커밋 번호, `train_pairs_sha256` 앞 8자리, qrels 종류(provisional/final)
4. 데이터를 다시 만들면 새 커밋으로 다시 공지(다른 데이터로 학습한 run끼리는 비교하지 않음)
5. val 조정이 끝나면 최종 qrels를 push·공지 → **2단계 시작**
