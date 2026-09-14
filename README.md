# Store Search AI — StoreSearch-KO v1

한국어 매장 검색 Dense Retrieval 프로젝트. 전국 가맹점 데이터(현재 214,043개, `stores_v003`)를 기반으로
자연어 query("통닭", "고기 파는 곳", "머리 자르는 곳" 등)에 대한 매장 검색 벤치마크와 파이프라인을 제공합니다.

## 핵심 원칙

1. Raw 파일(`data/raw/*.xlsx`)은 수정하지 않습니다. 새 데이터로 교체할 때는 새 파일명으로 추가하고
   기존 파일은 그대로 둡니다(`docs/EXTENDING_DATA.md` 참고).
2. 사업자번호/가맹점번호/법정동코드는 문자열로 취급합니다.
3. 가맹점번호는 결측·전화번호 형태가 섞여 있어 PK로 사용하지 않습니다.
4. 매장 PK(`store_id`)는 `data/registry/store_registry.parquet`에서 append-only로 발급되는 UUID이며,
   raw의 어떤 컬럼과도 1:1로 단정하지 않습니다. **이 레지스트리 파일은 절대 지우면 안 됩니다** — 지우면
   기존 매장들의 store_id가 전부 새로 발급되어, 이미 만들어 둔 qrels(query_id ↔ doc_id 매핑)가 깨집니다.
5. 취급품목 NULL은 삭제·기타로 채우지 않고 그대로 결측 처리합니다.
6. 전처리/벤치마크 구축/평가를 단계별 스크립트로 분리합니다(아래 파이프라인 참고).
7. **Document representation은 T1(`search_text_t1_minimal` = 가맹점명 + 취급품목)을 공식으로 사용합니다.**
   예: `가맹점명: 열매서점 / 취급품목: 서적`
8. **Train/Val/Test qrels 모두 사람이 직접 판정합니다.** Train은 애노테이터 1명의 단일 라벨링, Val/Test는
   사람 2명의 이중 라벨링 + adjudication을 거친 gold입니다. (한때 train만 query family의
   `positive_terms`/`boundary_terms` 규칙으로 자동 라벨링하는 weak supervision 방식을 썼으나, 같은
   데이터로 직접 비교한 결과 사람이 확정한 relevance=3 문서의 약 80%가 규칙 기반 방식에서는
   relevance=0으로 떨어지는 재현율 문제가 확인되어 사람 라벨링으로 되돌렸습니다 — 해당 스크립트는
   `archive/rule_based_train_labeling/`에 보존.) 자세한 이유는 아래 "Train/Val/Test 분할 방식"을 참고하세요.

## 설치

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

`pip install -e ".[embedding]"`는 dense encoder(torch/transformers/sentence-transformers)가 필요할 때만
추가로 설치하세요. `pyproject.toml`의 `requires-python`은 3.11을 기준으로 검증됐지만, 평가 스크립트
(13번)에 Python 3.12+ 호환 shim이 들어있어 `ir-measures`의 `ast.Num` 제거 이슈는 우회됩니다.

## 폴더 구조

```
configs/
  data/default.yaml              raw xlsx 스키마·컬럼 매핑·지역(시도) 별칭 테이블·검증 규칙
  benchmark/storesearch_ko_v1.yaml   벤치마크 경로/버전/파라미터(pooling, annotation, validation, evaluation)
  benchmark/query_families_v1.yaml   query family 정의 (생성물 — data/query/queryset_final.xlsx에서
                                  import_queryset_xlsx.py로 생성, 직접 편집 금지. docs/EXTENDING_DATA.md 참고)
  evaluation/default.yaml        공식 metric 목록 (문서화용 — 13_evaluate_run.py는 metric을 자체 상수로 갖고 있음)
  models/*.yaml                  비교 대상 임베딩 모델 설정 (zero-shot 비교/파인튜닝 후보)
src/store_search_ai/
  common/io.py                   yaml/엑셀 로딩 유틸
  data/                          전처리·registry·corpus·search_text·지역 판별 핵심 로직
  pipeline/common.py             scripts/*.py 공통 보일러플레이트 (yaml 로드, TREC 저장 등)
  models/                        임베딩 인코더 (BEIR 스타일, docs/MODELING.md 참고)
  retrieval/exact_search.py      exact cosine 검색 (ANN 이전 단계 모델 비교용)
scripts/01_*.py ~ scripts/15_*.py   파이프라인 본체 (docs/PIPELINE.md 참고)
scripts/import_queryset_xlsx.py    data/query/queryset_final.xlsx → query_families_v1.yaml 변환기(번호 없음, 05 이전에 1회성 실행)
scripts/prepare_finetune_dataset.py  train qrels+corpus → fine-tuning용 jsonl (번호 없음, docs/TRAINING.md 참고)
data/
  raw/stores_20260907.xlsx       원본 전국 데이터 (수정 금지)
  query/queryset_final.xlsx      팀이 작성한 최종 query family/질의 원본 (수정 금지, import_queryset_xlsx.py가 읽음)
  interim/ processed/ registry/  전처리 중간/최종 산출물 (registry 제외 전부 재생성 가능)
  corpus/store_corpus_v002.parquet   검색 대상 corpus (T1/T2/T3 템플릿 포함)
  finetune/train_pairs.jsonl     fine-tuning 학습쌍 (prepare_finetune_dataset.py 산출물, 재생성 가능)
benchmark/storesearch_ko_v1/
  queries.csv, annotation_guideline.md, qrels*.csv/.trec, benchmark_manifest.json
archive/rule_based_train_labeling/ 한때 썼던 규칙 기반 train 자동 라벨링 스크립트 (재현율 문제로 보류, 참고용)
models/                         fine-tuned 모델 가중치 (.gitignore 처리 — Colab에서 내려받은 걸 로컬에 둠)
tests/                          단위 테스트 (pytest)
colab/                          Colab(GPU)에서 임베딩 모델 인코딩/학습하는 스크립트 (colab/README.md 참고)
docs/
  PIPELINE.md                    15단계 실행 순서·인자·사람 개입 지점 (필독)
  EXTENDING_DATA.md               raw 데이터 확장 / query family 재정의 방법
  MODELING.md                    임베딩 모델 zero-shot 비교 구조 (BEIR 스타일)
  TRAINING.md                    Colab에서 fine-tuning 하는 방법 (Qwen3=ms-swift/LoRA, 나머지=sentence-transformers)
```

## 빠른 시작

```bash
pytest tests/ -q

make corpus   # 01~04를 필요한 만큼만 자동 재실행 (Makefile 참고)
```

또는 직접:

```bash
python scripts/01_profile_data.py --input data/raw/stores_20260907.xlsx
python scripts/02_preprocess_data.py --input data/raw/stores_20260907.xlsx
python scripts/03_analyze_items.py
python scripts/04_build_corpus.py
```

## 전체 파이프라인 실행 순서

자세한 입출력·플래그는 `docs/PIPELINE.md`를 보세요. 요약:

| 단계 | 스크립트 | 사람 개입 | 설명 |
|---|---|---|---|
| 1 | `01_profile_data.py` | 없음 | raw xlsx 프로파일링 리포트 |
| 2 | `02_preprocess_data.py` | 없음 | 정제 + store_id 발급 (`data/processed/`) |
| 3 | `03_analyze_items.py` | 없음 | 취급품목 텍스트 품질 리포트(정보성) |
| 4 | `04_build_corpus.py` | 없음 | 검색 corpus 생성 (T1/T2/T3) |
| 5 | `05_init_benchmark.py` | 없음 | `query_families_v1.yaml` → `queries.csv` |
| 6 | `06_generate_lexical_runs.py` | 없음 | TF-IDF/BM25 pooling run |
| 7 | `07_build_annotation_pool.py` | 없음 | candidate pool 생성 |
| 8 | `08_make_full_annotation_sheets.py` | 없음(시트만 생성) | train(A 단독)/val·test(A,B) 애노테이션 시트 생성 |
| — | (사람이 직접 라벨링) | **필요** | annotator가 train/val/test 시트를 채워 `*_completed.csv`로 저장 |
| 9 | `09_prepare_full_annotations.py` | 없음 | train 단일 라벨 → provisional qrels, val/test A/B 비교 + adjudication 대상 분리, agreement_report.json 생성 |
| — | (사람이 직접 조정) | **필요** | 3rd adjudicator가 val/test 불일치 건 확정 |
| 10 | `10_apply_adjudication_patch.py` | 없음 | adjudication 패치 반영 |
| 11 | `11_build_qrels.py` | 없음 | train + val/test(모두 사람) 병합 → 최종 qrels |
| 12 | `12_validate_benchmark.py` | 없음 | 무결성 검증 |
| 13 | `13_evaluate_run.py` | 없음 | 공식 evaluator (nDCG@10 등) |
| 14 | `14_run_model_eval.py` | 없음(GPU 필요) | 임베딩 모델(zero-shot/fine-tuned 공통) 인코딩 → 검색 → 13번 호출 |
| 15 | `15_score_model_runs.py` | 없음 | 여러 run을 모아 리더보드 생성 |

01~07은 사람 개입 없이 끝까지 자동 재실행됩니다(`make pool`). 08~10은 train/val/test 본 애노테이션 +
adjudication을 위한 실제 사람 작업이 필요한 구간입니다 — 이 구간을 건너뛰고 자동으로 생성하는 방법은
없습니다(TREC 스타일 pooling + double annotation(val/test)/single annotation(train) + adjudication
관례를 그대로 따름). calibration(애노테이터 사전 신뢰도 보정) 단계는 실제로 한 번도 안 쓰이고
family 목록이 낡아서 삭제했습니다 — 필요하면 git 이력에서 복원하되 family 목록은 다시 써야 합니다.

## Query family 추가/재정의

`configs/benchmark/query_families_v1.yaml`을 편집하세요. 현재 `gas_station`, `academy` family는 전국
데이터 전환 후 파이프라인이 끝까지 도는지 확인하기 위한 임시 추가분이며, 최종 구성은 팀 회의로 다시
정합니다. 편집 방법은 `docs/EXTENDING_DATA.md`를 참고하세요.

## Train/Val/Test 분할 방식

- 분할 단위는 **개별 query가 아니라 query family**입니다. 한 family(예: `chicken`)는 train/val/test 중
  정확히 하나에만 속하고, 그 family의 모든 variant(exact/synonym/paraphrase/colloquial)가 같은 split으로
  갑니다. `12_validate_benchmark.py`가 family가 두 split에 걸치지 않는지 검사합니다.
- **Corpus(매장 문서)는 분할하지 않습니다** — train/val/test 모두 동일한 전체 corpus를 대상으로
  검색합니다. BEIR/TREC 스타일 retrieval 벤치마크와 동일하게, 나뉘는 것은 문서가 아니라 **query(및 그
  정답 판정)**입니다.
- family를 나누는 이유는 **의도(카테고리) 단위의 일반화 성능**을 측정하기 위함입니다. "치킨" 계열
  query를 train과 test 모두에 넣으면 모델이 학습 때 본 것과 사실상 같은 개념을 test에서 다시 맞히는
  것이라 진짜 zero-shot 일반화를 측정하지 못합니다(leakage). family 단위로 완전히 분리하면 test는
  "학습 때 전혀 보지 못한 새로운 매장 카테고리"에 대한 검색 성능을 측정하게 됩니다 — MTEB/BEIR이
  embedding 모델을 미학습 도메인/태스크에 대해 평가하는 것과 같은 철학입니다.
- **train**: fine-tuning용 (query, positive doc, negative doc) 쌍을 만드는 데 씁니다. qrels는
  애노테이터 1명이 직접 판정한 라벨입니다(`08_make_full_annotation_sheets.py` → `09_prepare_full_annotations.py`).
  모델 성능을 "보고"하는 데는 쓰지 않으므로 val/test와 달리 이중 라벨링은 하지 않습니다.
- **val**: 체크포인트/템플릿(T1/T2/T3)/하이퍼파라미터 선택에만 씁니다. 사람이 이중 라벨링 +
  adjudication한 gold qrels입니다. 절대 gradient 학습에 쓰지 않습니다.
- **test**: 최종 설정이 다 정해지기 전까지 절대 보지 않는 held-out입니다. 마찬가지로 사람이 만든
  gold이며, 학습·하이퍼파라미터 선택·템플릿 선택 어디에도 쓰지 않습니다.

## 팀 공유 체크리스트 (Qwen3 학습 착수 직전)

Qwen3 임베딩 파인튜닝에 들어가기 전에 팀원과 아래를 공유하세요:

1. **이 코드 저장소 전체**(특히 `scripts/`, `src/`, `configs/`) — 데이터를 만든 코드 자체가 재현의
   기준입니다. 원본 데이터가 또 바뀌어도 `configs/data/default.yaml`의 `dataset_version`과
   `configs/benchmark/storesearch_ko_v1.yaml`의 `corpus_version`만 올리면 스크립트 수정 없이
   재실행됩니다.
2. **데이터 산출물**:
   - `data/corpus/store_corpus_v002.parquet` (+ `_manifest.json`) — 검색 대상 전체 corpus.
   - `benchmark/storesearch_ko_v1/queries.csv`, `annotation_guideline.md`
   - `benchmark/storesearch_ko_v1/qrels_train.csv`, `qrels_val.csv`, `qrels_test.csv`, `qrels.csv`
     (+ 대응 `.trec`), `benchmark_manifest.json` — **11_build_qrels.py 실행 후** 생성됩니다.
3. **raw 원본**(`data/raw/stores_20260907.xlsx`)은 용량이 커서 필수는 아니지만, 재현을 위해 공유 스토리지
   경로만이라도 팀과 합의해 두세요. 파생 산출물(2번)만 공유해도 파이프라인을 다시 돌릴 필요 없이 학습에
   바로 쓸 수 있습니다.
4. train qrels는 애노테이터 1명의 단일 라벨링, val/test는 사람 2명 이중 라벨링 + adjudication을 거친
   gold라는 점을 명시해서 공유하세요(위 "Train/Val/Test 분할 방식" 참고).

## 평가

```bash
python scripts/13_evaluate_run.py --run <run.csv> --tag <experiment_name>
```

Run CSV 스키마: `query_id,doc_id,rank,score,system`. Primary metric은 `nDCG@10`(부트스트랩 95% CI 포함).
