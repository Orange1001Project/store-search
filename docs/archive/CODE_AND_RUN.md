# 코드 구성과 실행 방법

이 저장소는 **오프라인 평가로 검색 구성을 고르는 곳**이다. 서비스(자바 백엔드)는 여기 코드를 그대로 쓰지 않고 `docs/BACKEND_HANDOFF.md`의
산출물과 동작을 옮긴다. 이 문서는 코드가 어디에 있고 무엇을 어떤 순서로 돌리는지만 적는다. 스크립트마다 머리말(docstring)에 입력·출력·규칙이
자세히 있으니, 세부는 그 파일을 열어 본다.

관련 문서: 판정·평가 절차 `docs/archive/EVALUATION.md`, 임베딩 학습 `docs/archive/TRAINING.md`, 실험 기록 `docs/archive/SERVICE_PIPELINE_PLAN.md`.

## 0. 한눈에

| 폴더 | 내용 |
|---|---|
| `src/store_search_ai/` | 라이브러리 코드(2절). 스크립트는 인자·파일 입출력만 하고 로직은 여기 둔다 |
| `scripts/` | 실행 스크립트. `01`~`16` = 기존 벤치마크 순서, 나머지 = 서비스 평가·실험 도구(3절) |
| `configs/` | 데이터(`data/`), 기존 벤치마크(`benchmark/`), 모델(`models/`), 서비스 쿼리셋(`query/service_queryset_v1.yaml`), 업종(`category/`), **서비스 정책(`service/search_policy_v1.yaml`, `brand_alias_v1.csv`)** |
| `data/` | raw xlsx(수정 금지), 전처리·코퍼스 parquet, 가게 ID 레지스트리, 지명 사전(`geo/`), 업종(`category/`), 쿼리 작성 파일(`query/`) |
| `benchmark/storesearch_ko_v1/` | 기존 벤치마크(업종 의도 쿼리) — 쿼리·판정·qrels |
| `benchmark/service_ko_v1/` | 서비스셋 — 쿼리, 사례(instances), 판정 라운드(`annotations/service_v*`), qrels, 주 평가셋, run |
| `results/` | 모델 평가, 서비스 평가(`service_eval/`), 파이프라인 실험(`service_pipeline/x1·x8·x23·p2`) |
| `colab/` | GPU 작업 노트북(4절) |
| `tests/` | pytest(374개). 정책 yaml ↔ 코드 상수 일치는 `test_search_policy.py` |
| `models/` | 내려받은 모델 가중치(git 제외) |

## 1. 환경 준비

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-lock.txt   # 팀과 같은 버전(권장)
pip install -e . --no-deps
pytest tests -q                   # 374 passed, 1 skipped (2026-11-10)
```

- 빠르게만 쓰려면 `pip install -e ".[dev]"`(pyproject의 범위 안 최신 버전 — 사람마다 버전이 달라질 수 있다).
- Windows에는 GNU make가 없어 `Makefile`을 그대로 못 쓴다 → `python scripts/...`를 직접 실행한다.
- 의존성을 올릴 때: pyproject 범위 수정 → `pip install -e ".[dev]" --upgrade` → 전체 테스트 → `pip freeze`로 lock 재생성(자기 자신 `-e git+...` 줄 제외).
- 콘솔이 cp949라 한글·기호 출력이 깨지면 `PYTHONIOENCODING=utf-8`.

## 2. 라이브러리 코드 (`src/store_search_ai/`)

| 모듈 | 하는 일 | 주요 파일 |
|---|---|---|
| `data/` 데이터 | raw 읽기·전처리·가게 ID 발급·코퍼스 | `preprocess.py`, `master.py`, `registry.py`(store_id 레지스트리, entity_fingerprint), `ids.py`, `region.py`, `corpus.py`, `search_text.py`(T1 = 가맹점명 + 취급품목), `items.py`, `text_cleaning.py`, `profile.py`, `item_analysis.py` |
| `data/` 기존 벤치마크 | 쿼리·pool·판정 시트·조정·qrels | `query_import.py`, `benchmark_init.py`, `annotation_pool.py`, `annotation_sheets.py`, `annotation_split.py`, `annotation_prep.py`, `adjudication_patch.py`, `qrels_builder.py`, `benchmark_validation.py`, `supplemental_round.py`, `finetune_dataset.py` |
| `data/` 서비스셋 | 쿼리 작성·가져오기, 사례, 반경 pool, qrels | `service_queryset.py`, `writer_sheets.py`, `service_import.py`, `service_instances.py`, `service_pool.py`(반경·필터 후보, `lexical_query`·`dense_query`, `branch_suffixes`), `service_qrels.py` |
| `data/` 지명·업종 | 공공데이터 지명 사전, 임시 업종 v0 | `gazetteer.py`, `category.py` |
| `query/` | 검색어 해석(지역·상호·브랜드·업종), 브랜드 별칭 | `understanding.py`(`QueryUnderstanding.parse`), `aliases.py`(`BrandAliases`) |
| `retrieval/` | 검색·점수 결합 | `exact_search.py`(정확 kNN), `lexical.py`(문자 BM25 등), `fusion.py`(min-max·가중합·RRF, `normalize_name`·`name_match`·`boost` = 상호 일치 가산), `expansion.py`(`SparseBM25` = 전국 BM25, LLM 확장 가산), `category_boost.py`(업종 가산 — 쓰지 않음) |
| `evaluation/` | 채점 | `evaluator.py`(기존 벤치마크 공식 채점), `service_eval.py`(서비스셋 지표·묶음), `threshold.py`(관련 확률 특성·로지스틱 적합), `model_evaluation.py` |
| `models/` | 임베딩 인코더·리더보드 | `sentence_transformer_encoder.py`, `base.py`, `model_eval.py`, `leaderboard.py`, `random_encoder.py`(더미) |
| `training/` | 미세조정 | `st_finetune.py`, `finetune.py` |
| `common/`, `pipeline/` | 입출력·HF 호환·라운드 경로 | `io.py`, `hf_compat.py`, `pipeline/common.py` |

### 서비스 검색 한 건이 코드에서 지나가는 길 (이식 기준)

| 단계(정책) | 코드 |
|---|---|
| 검색어 해석·지역·같은 이름 지명·상호 우선 | `query/understanding.py` `QueryUnderstanding.parse(query, center_lat, center_lon)` |
| 범위 안 후보(반경 / 법정동 코드 / 화면 사각형) | `data/service_pool.py` `candidates_within`, `filter_mask`, `candidates_filtered` |
| BM25 쿼리 만들기(지명·서술어·지점 접미사 빼기) | `service_pool.lexical_query`, `branch_suffixes` |
| 1단계: 임베딩 ∪ BM25, 상호 일치 +0.5 | `scripts/eval_service_pipeline.py` `first_stage`, `union_v1`, `fusion.boost` |
| 상호 일치 후보에 실제 코사인 | `eval_service_pipeline.augment_v1` |
| 브랜드 지점·상호 완전 일치 맨 위 | `eval_service_pipeline.brand_distance_sort`, `exact_name_sort` |
| LLM 확장 가산 | `retrieval/expansion.py` `add_expansion`, `SparseBM25` |
| 관련 확률 | `scripts/eval_x23.py` `relevance_features`, `apply_calibrator`(계수 `results/service_pipeline/x1/calibrator.json`) |
| 반경 확장·정렬·지도 | `scripts/eval_x23.py` `main`, `tier_order` |

## 3. 실행 순서

### 3-1 데이터 → 코퍼스 (사람 개입 없음, 다시 돌려도 됨)

```bash
python scripts/01_profile_data.py --input data/raw/stores_20260907.xlsx     # 프로파일 리포트
python scripts/02_preprocess_data.py --input data/raw/stores_20260907.xlsx  # 전처리 + store_id 발급
python scripts/03_analyze_items.py                                          # 품목 품질 리포트(선택)
python scripts/04_build_corpus.py                                           # data/corpus/<corpus_version>.parquet
```

- **store_id는 레지스트리(`data/registry/store_registry.parquet`)에 누적 발급**된다. entity_fingerprint(사업자번호 + 가맹점명 + 주소 해시)가
  같으면 같은 ID를 다시 쓰므로 데이터를 늘려도 기존 ID(= 평가 정답의 doc_id)는 바뀌지 않는다. **레지스트리 파일을 지우면 안 된다.**
- 새 raw 파일: `data/raw/`에 새 이름으로 추가(기존 파일 수정 금지) → `configs/data/default.yaml`의 `dataset_version`을 올리고 → 위 4개를
  `--input <새 파일>`로. 컬럼 이름이 바뀌면 같은 파일의 `column_map`을 고친다(`required_raw_columns`가 없으면 02가 멈춘다).
  코퍼스 내용이 달라지면 `configs/benchmark/storesearch_ko_v1.yaml`의 `corpus_version`도 올린다. 파일 경로는 두 버전에서 자동으로 정해진다.
- 시도 이름은 주소 첫 토큰을 `region_aliases`로 맞춘다. 표에 없는 표기는 `UNMAPPED`로 통과하니 보이면 한 줄 추가한다.

### 3-2 서비스 참조 데이터

```bash
python scripts/build_gazetteer.py --src <공공데이터 폴더>   # data/geo/gazetteer_v1.parquet (원본은 저장소 밖, 머리말에 파일 목록)
python scripts/build_store_category.py                    # data/category/store_category_v0.parquet
```

- 지점 접미사는 따로 파일이 없고 `service_pool.branch_suffixes(corpus)`가 코퍼스에서 계산한다(서비스는 결과를 파일·DB로 고정).
- LLM 확장어: `python scripts/export_x8_colab.py` → `colab/query_expansion.ipynb` → `results/service_pipeline/x8/expansions_<llm>.csv`.

### 3-3 서비스셋 평가 (판정 → 채점)

판정 기준·라운드 절차는 `docs/archive/EVALUATION.md`. 순서만 적으면:

```bash
python scripts/import_service_queries.py               # 작성 결과 → data/query/service_queries_v1.csv
python scripts/build_service_instances.py              # 사례(쿼리 × 가정위치) → instances.csv
python scripts/build_service_pool.py export            # Colab 입력 → colab/service_dense_runs.ipynb → runs/<모델>.csv
python scripts/build_service_pool.py runs              # 문자 BM25·키워드 run
python scripts/build_service_pool.py pool --round <라운드> --depth 10   # 판정 시트
python scripts/build_service_qrels.py                  # 판정 → 조정 목록 / qrels
python scripts/build_service_eval_set.py               # 주 평가셋(eval_set.csv)
python scripts/score_service_eval.py                   # 시스템 × 반경 × split × 묶음 채점 → results/service_eval/
```

### 3-4 검색 정책 평가 (지금 인계한 구성 재현)

```bash
python scripts/eval_service_pipeline.py --exp brand            # 1km 1단계(검색어 해석 + 상호 일치 + 브랜드 거리순), dev
python scripts/eval_relevance_threshold.py                     # 관련 확률 계수·임계값(dev) → results/service_pipeline/x1/
python scripts/build_x23_round.py export|runs|pool --round <라운드>   # 10km·지역·지도 판정 라운드
python scripts/eval_x23.py                                     # 정책대로 확장·지역·지도 채점(dev). --dump: 노출 목록
python scripts/eval_x8.py --final                                        # 채택 구성(LLM 확장 w 0.3 포함) 1km
# 최종 test(2026-11-09에 한 번 씀 — 새 판정 없이 다시 고르는 데 쓰지 않는다)
python scripts/eval_x23.py --split test
python scripts/eval_x8.py --split test --full-cosine --cosine-scope name --exact-name --only "exp+0.3 cat"
```

- 정책 값은 `configs/service/search_policy_v1.yaml`에서 읽는다. dev 비교용 덮어쓰기 인자(`--expansion-w`, `--brand-others-min` 등)는 `eval_x23.py --help`.
- 실험용 Colab 입력: `export_p2_cosine.py`(상호 일치 후보 코사인 → `colab/pair_cosine.ipynb`), `export_noregion.py`(지명 뺀 임베딩 쿼리), `exp_bm25_idf.py`(전국 IDF 확인).
- 판정 없이 쓰는 점검: `eval_query_understanding.py`(지역·의도 해석 정확도), `eval_category.py`(업종 신호).

### 3-5 기존 벤치마크·임베딩 학습

기존 벤치마크(업종 의도 쿼리, 01~16)와 임베딩 학습·모델 평가는 끝났다. 다시 돌릴 일이 있으면:

| 단계 | 명령 |
|---|---|
| 쿼리 | `import_queryset_xlsx.py`(xlsx → `configs/benchmark/query_families_v1.yaml`, yaml 직접 편집 금지) → `05_init_benchmark.py`. 쿼리를 빼려면 `configs/benchmark/inactive_queries_v1.yaml` |
| pool | `06_generate_lexical_runs.py` → `07_build_annotation_pool.py --round <이름>` |
| 판정 | `08_make_full_annotation_sheets.py` → (한 파일로 작업했으면 `split_completed_annotations.py`) → `09_prepare_full_annotations.py` → 조정 → `10_apply_adjudication_patch.py --patch <조정 완료본>` |
| qrels·검증 | `11_build_qrels.py --adjudication <완료본>` → `12_validate_benchmark.py --stage final` |
| 채점 | `13_evaluate_run.py --run <run.csv> --tag <이름>`(유일한 공식 채점 경로), 모델은 `14_run_model_eval.py --model-config configs/models/<모델>.yaml` → `15_score_model_runs.py` |
| 보충 판정 | `16_supplemental_round.py`, 후보 일괄 판정 `collect_judging_candidates.py --make`, qrels가 바뀌면 `rescore_evaluations.py` |
| 학습 | `docs/archive/TRAINING.md`(`prepare_finetune_dataset.py`, `pack_for_colab.py`, `colab/train_eval.ipynb`, `import_colab_results.py`) |

- 판정 원칙: val/test는 A·B 독립 이중 판정, 점수를 평균 내지 않고 불일치는 사람이 조정한다.
- 이 단계들은 Makefile 타깃(`make corpus`, `make pool`, `make build-qrels` 등)으로도 있다(macOS/Linux).

## 4. Colab 노트북

| 노트북 | 쓰는 곳 |
|---|---|
| `train_eval.ipynb` | 임베딩 학습·평가(`docs/archive/TRAINING.md`) |
| `service_dense_runs.ipynb` | 서비스셋 사례의 반경 안 임베딩 run |
| `query_expansion.ipynb` | LLM 쿼리 확장어 생성(Qwen2.5-14B) |
| `pair_cosine.ipynb` | 임베딩 상위 밖 후보의 실제 코사인 |
| `rerank_scores.ipynb` | reranker 점수(쓰지 않기로 함 — 기록용) |

Drive 경로·실행 방법은 `colab/README.md`.
