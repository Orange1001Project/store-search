# StoreSearch-KO v1 — 파이프라인 실행 순서

`scripts/01_*.py` ~ `scripts/15_*.py`를 어떤 순서·인자로 실행해야 하는지 정의합니다. 번호 = 실행
순서 = 1회 실행입니다.

## 0. 환경 준비 (최초 1회)

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

`scripts/13_evaluate_run.py`에 Python 3.12+ 호환 shim이 들어있어서(구버전 `ir-measures`가 3.12에서
제거된 `ast.Num`을 쓰는 문제 우회) 3.11 고정은 아니지만, 검증은 3.11 기준으로 이뤄졌습니다.

## 1. 데이터 전처리 ~ Corpus 구축 (사람 개입 없음, 전부 재실행 가능)

```bash
python scripts/01_profile_data.py --input data/raw/stores_20260907.xlsx
python scripts/02_preprocess_data.py --input data/raw/stores_20260907.xlsx
python scripts/03_analyze_items.py
python scripts/04_build_corpus.py
```

- 01: raw xlsx 프로파일링 리포트만 생성 (`artifacts/reports/data_profile.json`)
- 02: raw → `data/interim/store_records_{dataset_version}.parquet` →
  `data/processed/stores_master_{dataset_version}.parquet`. 이 단계에서
  `data/registry/store_registry.parquet`에 매장별 영구 `store_id`(UUID)가 발급/누적됩니다.
  **레지스트리는 append-only이므로 재실행해도 기존 매장의 store_id가 바뀌지 않습니다.**
  단일 시트 데이터의 지역(시도)은 주소에서 자동 파생됩니다(`configs/data/default.yaml`의
  `region_aliases`, `src/store_search_ai/data/region.py`).
- 03: 취급품목 텍스트 품질 리포트 (`artifacts/reports/item_analysis_{dataset_version}/`) — 파이프라인
  진행에 필수는 아니지만 taxonomy 정비에 사용
- 04: `data/corpus/{corpus_version}.parquet` 생성 (T1/T2/T3 검색 텍스트 템플릿 포함). **본 프로젝트는
  T1(`search_text_t1_minimal` = 가맹점명+취급품목)을 공식 document representation으로 사용**

`dataset_version`(`configs/data/default.yaml`)/`corpus_version`(`configs/benchmark/storesearch_ko_v1.yaml`)만
올리면 파일명이 자동으로 갱신되므로, 데이터가 또 바뀌어도 스크립트 자체는 수정할 필요가 없습니다.

## 2. 벤치마크 Query Set 초기화

```bash
python scripts/05_init_benchmark.py
```

`configs/benchmark/query_families_v1.yaml`을 읽어 `benchmark/storesearch_ko_v1/queries.csv` +
`annotation_guideline.md`를 생성합니다. **이 yaml은 직접 편집하는 파일이 아니라
`scripts/import_queryset_xlsx.py`가 `data/query/queryset_final.xlsx`로부터 생성하는 산출물입니다**
(자세한 방법은 `docs/EXTENDING_DATA.md` 참고, 질의 원본은 문서 하단 "Query family 원본" 참고).

## 3. Pooling (lexical) — 사람 개입 없음

```bash
python scripts/06_generate_lexical_runs.py
python scripts/07_build_annotation_pool.py --round lexical_v1
```

- 06: TF-IDF(char/word) + BM25 세 시스템으로 top-40 lexical run을 생성 (`benchmark/storesearch_ko_v1/runs/pooling/`)
- 07: 위 run들을 합쳐 애노테이션 대상 후보 pool을 만듭니다 (`candidate_pool_internal.csv`).
  **이 스크립트는 `--round` 인자로 여러 번 누적 호출 가능**합니다 (예: 나중에 dense retrieval 결과로 pool을
  확장하고 싶다면 `--round dense_round1`로 다시 실행).

## 4. 본 애노테이션 (Full annotation) — **사람 개입 필요**

```bash
python scripts/08_make_full_annotation_sheets.py
```

- train: 애노테이터 A만 단일 라벨링 — training signal이므로 모델 성능을 "보고"하는 데는 쓰지
  않아 시간 절약을 위해 단일 라벨링으로 처리
- val/test: 애노테이터 A, B 모두 독립적으로 라벨링

같은 내용을 두 가지 형태로 만들어 둔다(어느 쪽을 채워도 됨):
- split별 파일: `annotation_A_train.csv`/`_val.csv`/`_test.csv`, `annotation_B_val.csv`/`_test.csv`
- **A/B 각자 한 파일로 몰아 작업하고 싶으면**: `annotation_A_all.csv`(A가 train+val+test 전체를
  한 파일에서 작업), `annotation_B_val_test.csv`(B가 val+test를 한 파일에서 작업)

**split별 파일로 작업한 경우** — 채운 뒤 그대로 `*_completed.csv`로 저장:

```
benchmark/storesearch_ko_v1/annotations/full_annotation_v1/completed/
  annotation_A_train_completed.csv
  annotation_A_val_completed.csv
  annotation_A_test_completed.csv
  annotation_B_val_completed.csv
  annotation_B_test_completed.csv
```

**combined 파일(`_all`/`_val_test`)로 작업한 경우** — `annotation_A_all_completed.csv`,
`annotation_B_val_test_completed.csv`로 저장한 뒤 아래로 5개 split별 파일로 쪼갠다(같은
`completed/` 폴더에 넣으면 인자 없이 실행됨):

```bash
python scripts/split_completed_annotations.py
```

이후 공통:

```bash
python scripts/09_prepare_full_annotations.py
```

이 스크립트가 하는 일:
- train: 단일 라벨을 그대로 provisional qrels로 변환 (`qrels/provisional_v1/qrels_train_provisional.csv`)
- val/test: A·B 라벨을 비교해서 **일치하는 것은 자동 확정**, **불일치(`needs_adjudication=True`)는 사람이
  봐야 할 목록**을 `analysis/adjudication_val_test_needed_only.csv`로 분리 저장
- val+test 전체의 이중 라벨링 커버리지/합치도(Cohen's kappa 등)를 `benchmark_dir/agreement_report.json`에
  저장 — `12_validate_benchmark.py --stage final`이 이 파일을 확인합니다.

## 5. Adjudication (이견 조정) — **사람 개입 필요**

`adjudication_val_test_needed_only.csv`를 3rd adjudicator(또는 원 애노테이터 협의)가 검토하여
`final_relevance`, `human_adjudication_note`, (제외할 경우) `exclude_from_gold`를 채운 뒤
`adjudication_val_test_needed_only_completed.csv`로 저장합니다.

```bash
python scripts/10_apply_adjudication_patch.py \
  --patch benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/adjudication_val_test_needed_only_completed.csv
```

→ `adjudication_val_test_full_completed.csv` (전체 val/test 최종 판정: 자동 합의분 + 조정분 병합) 생성.

**주의**: "A/B 점수를 평균 내지 않는다"가 원칙입니다 (`09_prepare_full_annotations.py`가 요약에 명시). 반드시
`needs_adjudication=True`인 모든 행을 사람이 확정한 뒤 다음 단계로 넘어가야 합니다.

## 6. 최종 Qrels 빌드 + 검증 + 평가

```bash
python scripts/11_build_qrels.py \
  --adjudication benchmark/storesearch_ko_v1/annotations/full_annotation_v1/analysis/adjudication_val_test_full_completed.csv

python scripts/12_validate_benchmark.py --stage final
python scripts/13_evaluate_run.py --run <모델_run.csv> --tag <실험명>
```

- 11: `queries.csv`(active만) + adjudication 완료본(val/test) + 4절에서 만든 provisional train qrels를
  합쳐 `qrels_train.csv/.trec`, `qrels_val.csv/.trec`, `qrels_test.csv/.trec`, `qrels.csv/.trec`,
  `benchmark_manifest.json`을 `benchmark/storesearch_ko_v1/` 바로 아래(서브폴더 없이) 생성합니다.
- 12: 중복/미판정 쿼리/스키마 무결성 검증. `--stage final`에서는 최소 쿼리 수, double annotation
  coverage 등도 검사합니다.
- 13: 공식 evaluator. `--qrels`(기본값 `qrels_val.trec`), `--run`, `--tag` 필요. Primary metric은
  `nDCG@10`, bootstrap 95% CI 포함.

## 7. 모델 평가 — zero-shot 비교, 이후 fine-tuning 평가에도 재사용 (선택)

```bash
python scripts/14_run_model_eval.py --model-config configs/models/bge_m3.yaml --split val
python scripts/15_score_model_runs.py --split val
```

`docs/MODELING.md` 참고. Fine-tuning 이후에도 이 두 스크립트를 그대로 써서 fine-tuned 모델을
평가합니다(`docs/TRAINING.md` 참고) — 그래서 이름에 "zero_shot"을 넣지 않았습니다.

## 사람 개입이 필요한 범위

01~07(전처리~corpus~lexical pooling)까지는 데이터가 바뀌어도 사람 개입 없이 끝까지 재실행됩니다.
**08~10(train/val/test 본 애노테이션 + adjudication)은 실제 사람이 거쳐야** 최종
`qrels_train.csv`/`qrels_val.csv`/`qrels_test.csv`가 나옵니다. 이 과정을 건너뛰고 자동으로 생성하는
방법은 없습니다 — TREC 스타일 pooling + double annotation(val/test) + single annotation(train) +
adjudication 방식을 그대로 따른 설계입니다.

**calibration 단계는 삭제했습니다.** 한때 08~10번이 calibration(애노테이터 간 사전 신뢰도 보정)
단계였지만, 실제로 한 번도 쓰지 않았고(바로 본 애노테이션으로 진행) 하드코딩된 family 목록이
예전 영문 이름 그대로라 지금 데이터로는 실행 자체가 안 됐습니다. 필요해지면 git 이력(calibration
관련 커밋)에서 복원하되, family 목록은 현재 `query_families_v1.yaml` 기준으로 다시 써야 합니다.

**규칙 기반(rule-based) train 자동 라벨링을 시도했다가 되돌린 이력**: 한때 `08_auto_label_train_qrels.py`로
query family의 `positive_terms`/`boundary_terms` 문자열 매칭만으로 train qrels를 자동 생성하는 방식을
썼습니다(weak supervision). 같은 대전/세종 corpus·같은 term 정의로 사람이 만든 기존 train qrels와
직접 비교해본 결과, 사람이 `relevance=3`으로 확정한 문서의 약 80%가 이 방식에서는 `relevance=0`으로
떨어지는(재현율이 매우 낮은) 문제가 확인되어, 다시 사람 라벨링 방식(현재 문서의 4~5절)으로 되돌렸습니다.
해당 스크립트와 상세 내용은 `archive/rule_based_train_labeling/`에 보존되어 있습니다.

## Query family 원본

`configs/benchmark/query_families_v1.yaml`은 손으로 편집하는 파일이 아니라
`scripts/import_queryset_xlsx.py`가 `data/query/queryset_final.xlsx`(팀이 작성한 최종 질의
시트)로부터 생성합니다. 질의를 추가/수정하려면 xlsx를 고친 뒤 이 스크립트를 다시 돌리세요
(자세한 절차는 스크립트 상단 docstring 참고). yaml을 직접 고치면 다음 xlsx 재실행 때 덮어써집니다.
