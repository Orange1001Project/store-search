# StoreSearch-KO v1 — 파이프라인 코드 상세 레퍼런스

`docs/PIPELINE.md`이 "몇 번을 언제, 어떤 인자로, 사람이 언제 개입해서 돌리는가"를 다룬다면,
이 문서는 **그 안에서 코드가 실제로 무엇을 읽고 어떤 원리로 무엇을 계산해서 어디에 쓰는지**를
스크립트 단위로 뜯어봅니다. 회의에서 "이 단계가 왜 이렇게 동작하나요", "이 파일은 어디서
나온 거예요" 같은 질문에 코드 근거를 대면서 답할 수 있도록 만든 문서입니다.

번호 순서(01~15)대로 정리했고, 번호 없는 유틸리티 3개를 실제 실행 순서상 자리에 끼워 넣었습니다:
`import_queryset_xlsx.py`(05번 이전), `split_completed_annotations.py`(08번과 09번 사이),
`prepare_finetune_dataset.py`(15번 이후, fine-tuning 준비 단계). 각 절은 다음 다섯 항목으로
구성됩니다: **한 줄 요약 / 입력 파일 / 핵심 로직 / 출력 파일 / 사용하는 src/ 코드**.

모든 경로·설정값은 현재 저장소의 `configs/data/default.yaml`(`dataset_version: stores_v003`),
`configs/benchmark/storesearch_ko_v1.yaml`(`corpus_version: store_corpus_v002`,
`benchmark_dir: benchmark/storesearch_ko_v1`) 기준입니다.

**참고**: 한때 08~10번이 calibration(애노테이터 사전 신뢰도 보정) 단계였지만 삭제했습니다 —
자세한 이유는 문서 하단 FAQ Q6 참고.

---

## `01_profile_data.py`

**한 줄 요약**: raw xlsx를 아무것도 바꾸지 않고 읽어서 시트별/전체 프로파일링 리포트만 만든다.

**입력 파일**
- `--input`(필수): raw xlsx 경로(예: `data/raw/stores_20260907.xlsx`)
- `--config`(기본 `configs/data/default.yaml`): `excel.sheets`에 정의된 시트 목록만 읽음

**핵심 로직**
`read_excel_sheets()`로 설정된 시트들을 시트당 (sheet_name, source_region, DataFrame)으로 읽고,
시트별로 `profile_frame()`을 돌려 컬럼별 결측률/유니크 개수 + 컬럼별 특화 통계(사업자번호 중복,
가맹점번호 결측, 취급품목 결측/상위값, 시장분류코드 분포)를 계산한다. 그 다음 시트들을 하나로
합쳐 동일한 프로파일을 "COMBINED" 기준으로 한 번 더 계산하고, 시트(=지역) 별 행 수 분포도 남긴다.
가공은 전혀 하지 않는 순수 진단 단계 — 이후 단계(02~)의 입력이 되지 않는다.

**출력 파일**
- `--output`(기본 `artifacts/reports/data_profile.json`, **`dataset_version`으로 버전이 안 붙는
  공용 경로**라서 다른 데이터셋으로 다시 돌리면 이전 결과를 덮어쓴다 — 여러 데이터셋을 동시에
  비교 보관하려면 `--output`을 직접 다르게 지정해야 함)

**사용하는 src/ 코드**
- `store_search_ai.common.io.load_yaml` — yaml 로드
- `store_search_ai.common.io.read_excel_sheets` — 시트 읽기(시트 설정에 `source_region`이 고정돼
  있으면 그 값을, 없으면 `None`을 반환해 호출부가 주소 기반 파생을 하도록 신호를 준다)
- `store_search_ai.data.profile.profile_frame` — 프로파일링 계산 본체

---

## `02_preprocess_data.py`

**한 줄 요약**: raw xlsx → 정제된 source record → `store_id` 발급 → 매장 단위 병합(Master)까지
한 번에 수행하는, 파이프라인에서 가장 무거운 전처리 단계.

**입력 파일**
- `--input`(필수): raw xlsx
- `--config`(기본 `configs/data/default.yaml`): `column_map`, `required_raw_columns`,
  `region_aliases`, `validation`(위경도/법정동코드/사업자번호 자릿수), `search_text_templates`,
  `valid_market_types`
- `--registry`(기본 `data/registry/store_registry.parquet`) — **append-only 공유 자원**. 이전에
  발급된 `entity_fingerprint → store_id` 매핑을 그대로 이어받는다.

**핵심 로직**
시트별로 `canonicalize()`를 돌려 한글 원본 컬럼명 → 내부 컬럼명 매핑, 문자열 정제, 주소 정제,
지역(시도) 판별, 위경도 검증(0,0은 결측으로 간주), 법정동코드/사업자번호 자릿수 검증, 시장분류
검증, 카드/모바일결제 Y/N 정규화, 취급품목 토큰화, 그리고 `entity_fingerprint =
sha256(사업자번호|가맹점명.casefold|주소.casefold)`를 계산한다. 지역 판별은 시트에
`source_region`이 고정돼 있으면 그 값을 그대로 쓰고, 없으면(현재 전국 단일 시트 방식)
주소 첫 토큰을 `region_aliases`로 정규화한다 — alias에 없으면 조용히 `UNMAPPED` 처리(파이프라인이
죽지 않음).

`entity_fingerprint`는 **PK가 아니라 중복 판단용**이다. 진짜 영구 PK인 `store_id`(UUID)는
`assign_store_ids()`가 registry에서 fingerprint를 찾아보고, 있으면 재사용, 없으면 새로 발급해서
registry에 추가한다 — 그래서 데이터가 늘어나도 기존 매장의 `store_id`는 절대 바뀌지 않는다(이미
만들어둔 qrels의 query_id↔doc_id 매핑이 깨지지 않는 이유).

같은 `store_id`로 묶인 원본 행이 여러 개면 `build_store_master()`가 병합한다: 취급품목은
합집합(다른 표현이 있어도 다 모음), merchant_no/좌표/카드결제/모바일결제는 **서로 다른 값이
2개 이상이면 임의로 하나를 고르지 않고 결측 처리 + conflict 플래그**를 남긴다("판매점 정보가
서로 다른데 시스템이 멋대로 하나를 골라버리는" 실수를 방지).

**출력 파일**
- `data/interim/store_records_{dataset_version}.parquet` — canonicalize 직후, 중복 포함 전체
  source record
- `data/processed/stores_master_{dataset_version}.parquet` — store_id 단위로 병합된 최종 마스터
- `data/registry/store_registry.parquet` — **덮어쓰지 말고 절대 지우면 안 되는** append-only
  store_id 발급 대장
- `artifacts/reports/preprocess_summary_{dataset_version}.json` — 행 수/결측률/충돌 건수 요약
- (있을 때만) `artifacts/reports/duplicate_candidates_{dataset_version}.parquet`,
  `artifacts/reports/master_merge_conflicts_{dataset_version}.csv`

**사용하는 src/ 코드**
- `store_search_ai.common.io.load_yaml`, `read_excel_sheets`
- `store_search_ai.data.preprocess.canonicalize` — 시트 1개 정제(위 핵심 로직 대부분이 여기)
- `store_search_ai.data.preprocess.find_duplicate_candidates` — 같은 store_id/사업자번호로 묶이는
  행 진단
- `store_search_ai.data.text_cleaning.{normalize_spaces, clean_address, clean_digits,
  normalize_yn}` — canonicalize 내부에서 사용
- `store_search_ai.data.ids.build_entity_fingerprint` — fingerprint 계산
- `store_search_ai.data.items.{parse_item_tokens, has_ambiguous_suffix}` — 취급품목 토큰화
- `store_search_ai.data.region.derive_region_series` — 주소 → 시도 파생
- `store_search_ai.data.search_text.attach_templates` — T1/T2/T3 검색 텍스트 생성(마스터
  병합 후 취급품목이 바뀌므로 병합 전/후 두 번 호출됨)
- `store_search_ai.data.registry.assign_store_ids` — store_id 발급/재사용
- `store_search_ai.data.master.build_store_master` — 매장 단위 병합 + 충돌 감지

---

## `03_analyze_items.py`

**한 줄 요약**: 취급품목(item) 텍스트 품질을 진단하는 리포트 생성 — 파이프라인 진행에 필수는
아니고 taxonomy 정비용 정보성 단계.

**입력 파일**
- `--config`(기본 `configs/data/default.yaml`)에서 `dataset_version`만 읽음
- `--input`(기본 `data/processed/stores_master_{dataset_version}.parquet`)

**핵심 로직**
`item_tokens`를 explode해서 토큰별 빈도(`item_token_counts`), 원본 `item_raw` 값별 빈도, 지역별
토큰 빈도를 집계한다. 그 외 데이터 품질 신호를 개별적으로 뽑아낸다: 취급품목 결측 매장 목록,
매장 하나에 서로 다른 item 표현이 섞인 충돌 매장(`item_conflict`), 80자 이상 지나치게 긴 표현,
괄호 불균형(`has_unbalanced_parentheses` — 여닫는 괄호 수가 안 맞는 행), 잔여 HTML 엔티티
(`&amp;` 등, 원본/정제본 각각 검사), 노이즈 후보 토큰(구두점만 있는 토큰 등), "기타/서비스/판매"
같은 정보량이 낮은 표현. 마지막으로 롱테일 통계(전체 대비 상위 10/50/100개 토큰이 차지하는
비율, singleton 토큰 비율)를 계산한다.

**출력 파일** (전부 `artifacts/reports/item_analysis_{dataset_version}/` 밑)
`item_token_counts_*.csv`, `item_raw_counts_*.csv`, `item_token_counts_by_region_*.csv`,
`missing_item_stores_*.csv`, `item_conflict_stores_*.csv`, `long_item_values_*.csv`,
`unbalanced_parentheses_*.csv`, `html_entity_items_*.csv`, `clean_html_entity_items_*.csv`,
`low_information_tokens_*.csv`, `item_analysis_summary_*.json`

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config` (dataset_version 읽기용) — 그 외에는 pandas/정규식만
  사용하는 순수 분석 스크립트

---

## `04_build_corpus.py`

**한 줄 요약**: 매장 마스터에서 실제 검색 대상이 될 corpus(document 집합)를 뽑아낸다.

**입력 파일**
- `--config`(기본 **`configs/benchmark/storesearch_ko_v1.yaml`** — 03번까지와 달리 04번부터는
  benchmark config에서 `dataset_version`/`corpus_version`을 읽는다)
- `--input`(기본 `data/processed/stores_master_{dataset_version}.parquet` = 현재
  `stores_master_stores_v003.parquet`)

**핵심 로직**
`store_id` 중복/NULL이 있으면 즉시 에러(코퍼스 문서 ID의 유일성 보장). 마스터에서 검색/평가에
필요한 컬럼만 골라 corpus 스키마를 만들고 `doc_id = store_id`를 명시적으로 추가한다(같은 값이지만
"검색 문서 ID"라는 역할을 이름으로 분명히 함). 각 템플릿(T1/T2/T3) 텍스트의 SHA256을
`content_hash_t{1,2,3}`로 남겨두는데, 이는 지금 당장 쓰이진 않고 향후 "텍스트가 안 바뀐 매장은
재임베딩 생략" 같은 증분 임베딩 최적화를 위한 훅이다.

**출력 파일**
- `data/corpus/{corpus_version}.parquet` = 현재 `data/corpus/store_corpus_v002.parquet` — 컬럼:
  `doc_id, store_name, market_name, market_type, item_text, has_item, address, latitude,
  longitude, geo_status, legal_dong_code, source_region, card_payment, mobile_payment,
  search_text_t1_minimal, search_text_t2_market, search_text_t3_market_type,
  dataset_version, corpus_version, content_hash_t1/t2/t3`
- `data/corpus/{corpus_version}_manifest.json` — 문서 수, 결측 item/geo 문서 수, 템플릿 설명

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config` — 그 외 로직은 스크립트 안에 직접 구현(pandas만 사용)

---

## `import_queryset_xlsx.py` *(번호 없는 유틸리티, 05번 이전에 실행)*

**한 줄 요약**: 팀이 작성한 `data/query/queryset_final.xlsx`(질의 원본)를
`configs/benchmark/query_families_v1.yaml`(05번이 실제로 읽는 파일)로 변환한다. 이 xlsx가 바뀔
때마다 05번보다 먼저, 사람이 검토 후 재실행하는 저작 도구다 — 01~15 실행 순서 자체에는
속하지 않는다.

**입력 파일**
- `--input`(기본 `data/query/queryset_final.xlsx`) — 시트 두 개를 읽음: **통합질의**(질의, 패밀리,
  대분류, 유형(T1~T6), 태그, 출처, 합의, 원본유형, 현행 결과, 관련 가맹점, 함정), **패밀리목록**
  (패밀리, 대분류, 우선순위 등)
- `--existing-families`(기본 `--output`과 동일한 `query_families_v1.yaml`) — **split 상속의
  기준**. 재실행해도 이미 배정된 family의 train/val/test가 안 흔들리게 하기 위해 현재 파일을
  먼저 읽는다.

**핵심 로직**
`RECLASSIFY_QUERIES` 딕셔너리로 xlsx 병합 과정에서 패밀리가 잘못 배정된 게 확인된 질의를
정정한다(예: "일본 음식 먹을 곳"이 한식에 잘못 들어간 것을 원본유형 태그로 판단해 일식으로
재배정, "(미판정)"이던 5행을 기존 family 또는 신설 family `복합`으로 배정 — 이 판단은 자동
추론이므로 스크립트 실행 로그에 팀 검토를 요청하는 경고를 남긴다). 재배정 후에도 "(미판정)"이
남아 있으면 즉시 에러(새로 발견된 미분류 행은 `RECLASSIFY_QUERIES`에 추가해야 함).

**family당 variant 최소 개수 제한이 없다**(팀 결정 — xlsx의 548개 질의를 전부 살림). split은
두 단계로 정한다: (1) 기존 yaml에 같은 한글 family 이름이 이미 있으면 그 split을 그대로
물려받고, (2) 없으면 `원본유형`의 영문 slug(예: `chicken`, `fruit`)로 기존 yaml과 대응시켜
물려받는다(완전히 새 yaml 체계로 갈아탈 때 대비). 그래도 대응이 안 되는 완전 신규 family만
대분류별로 균형 잡힌 무작위 배정을 한다(seed 고정, 카테고리 쏠림 방지). `positive_terms`는
그 family의 T1(정확표기)/T2(동의어) 질의 텍스트, `boundary_terms`는 `함정` 컬럼 값에서 뽑는다
(둘 다 pooling 후보 발굴에만 쓰이고 relevance 판정에는 영향 없음). `intent_definition`은
"{대분류} 중 '{family}'을(를) 판매·제공하는 매장" 형태로 초안만 자동 생성한다(사람 검토 필요).

**출력 파일**
- `--output`(기본 `configs/benchmark/query_families_v1.yaml`) — **이 파일을 직접 손으로 편집하면
  안 된다.** xlsx를 고치고 이 스크립트를 다시 돌리는 게 유일한 편집 경로다.

**사용하는 src/ 코드**
- 없음(순수 pandas + PyYAML — 이 스크립트 자체가 `configs/benchmark/query_families_v1.yaml`을
  만드는 도구라 `store_search_ai.pipeline.common.load_config`도 쓰지 않고 yaml을 직접 읽고 쓴다)

---

## `05_init_benchmark.py`

**한 줄 요약**: `query_families_v1.yaml`(`import_queryset_xlsx.py`가 생성하는 파일)로부터
`queries.csv`를 생성한다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `--families`(기본 `configs/benchmark/query_families_v1.yaml`) — **직접 편집하는 파일이 아니라
  `import_queryset_xlsx.py`의 생성물**(`docs/EXTENDING_DATA.md` 참고)

**핵심 로직**
family마다: family 이름 중복 금지, `split`은 train/val/test 중 하나만, **최소 1개 이상의 query
variant 필요**(원래는 3개 이상이었다가 팀 결정으로 완화됨). 각 query는
`query_id = q_{family}_{순번:02d}` 형식으로 자동 생성되고, 정규화된(공백 정리+casefold) 쿼리
텍스트가 파일 전체에서 중복되면 에러. `positive_terms`/`boundary_terms`는 파이프
구분 문자열로 직렬화되어 `pool_positive_terms`/`pool_boundary_terms` 컬럼에 들어가는데, 이 값은
**06~07단계의 pooling 후보 발굴에만 쓰이고 relevance 판정 자체에는 영향을 주지 않는다**(모든
split에서 relevance는 사람이 직접 판정).

**출력 파일** (전부 `benchmark_dir` = `benchmark/storesearch_ko_v1/` 밑)
- `queries.csv` — 스키마: `query_id, query, split, query_family, query_type, intent_definition,
  pool_positive_terms, pool_boundary_terms, query_set_version, status`
- `annotation_guideline.md` — 스크립트에 하드코딩된 `GUIDELINE` 문자열을 그대로 저장(0~3 등급
  정의, 판단 원칙, blind annotation 규칙, AI 보조 사용 범위)
- `query_manifest.json` — 총 쿼리/family 수, split별 분포, `queries.csv`와 families yaml의
  sha256(재현성 추적용)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`, `sha256_file`

---

## `06_generate_lexical_runs.py`

**한 줄 요약**: 사람 개입 없이, 3개의 서로 다른 lexical(어휘 기반) retrieval 시스템으로
각 쿼리의 top-40 후보를 뽑아 pooling 재료를 만든다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`) → `corpus_path`, `benchmark_dir`,
  `pooling.run_depth`(=40)
- corpus 전체(`data/corpus/store_corpus_v002.parquet`), active queries(`queries.csv`)

**핵심 로직**
document 텍스트는 `store_name + " " + item_text`(T1과 개념적으로 동일한 필드 조합, 다만 이
스크립트는 `search_text_t1_minimal` 컬럼을 그대로 쓰지 않고 즉석에서 다시 조합한다)로 고정한다.
세 시스템을 각각 corpus 전체에 fit한다: **char TF-IDF**(char_wb, 2~5-gram), **word TF-IDF**
(1~2-gram, 정규식 토큰), **BM25Okapi**(정규식 토큰 `[0-9A-Za-z가-힣]+`). 쿼리마다 세 시스템 각각의
점수를 계산해서 **score>0인 문서만** top-40으로 남긴다(0점 이하는 "lexical overlap이 아예 없다"는
뜻이라, 억지로 채우면 무의미한 문서가 pool을 오염시키기 때문 — random negative는 07에서 별도
채널로 명시적으로 뽑는다).

**출력 파일** (`benchmark_dir/runs/pooling/` 밑)
- `char_tfidf_v1.csv/.trec`, `word_tfidf_v1.csv/.trec`, `bm25_regex_v1.csv/.trec`
- `lexical_run_manifest.json` — 시스템별 통계(결과 있는/없는 쿼리 수, 평균 결과 수 등)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_active_queries`, `load_config` — 그 외 TF-IDF/BM25 로직은
  `sklearn`/`rank_bm25`를 스크립트에서 직접 사용(전용 src 모듈 없음)

---

## `07_build_annotation_pool.py`

**한 줄 요약**: lexical run + 규칙 기반 targeted 채널 + 결정적 random negative를 합쳐서
**사람이 실제로 라벨링할 후보 pool**(candidate_pool_internal.csv)을 만든다. "pooling"의 핵심 단계.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`) → `pooling.run_depth`,
  `targeted_per_term`(=5), `random_per_query`(=8), `random_seed`(=20260831)
- `--round`(필수, 예: `lexical_v1`, `dense_round1`) — 이 라운드 이름이 각 후보의
  `first_seen_round`/`last_updated_round`에 기록된다
- `benchmark_dir/runs/pooling/*.csv`(06의 산출물), corpus, active queries, 그리고 **이전
  `candidate_pool_internal.csv`가 있으면 그 위에 누적**(라운드를 여러 번 돌려도 이전 후보가
  사라지지 않음)

**핵심 로직 — "pooling"이 실제로 하는 일**: 한 쿼리에 대해 코퍼스 21만 건 전체를 사람이 다
판정할 수는 없으니, **여러 독립적인 검색 방법이 "관련 있어 보인다"고 지목한 문서들의 합집합**만
사람 앞에 놓는다(TREC 스타일 pooling). 이번 스크립트가 합치는 채널은 세 가지다:
1. **`run:{system}`** — 06의 세 lexical run 각각의 상위 40개(그 시스템이 실제로 찾은 것)
2. **`target:positive:{term}`/`target:boundary:{term}`** — `queries.csv`의
   `pool_positive_terms`/`pool_boundary_terms`를 취급품목/가맹점명에 직접 문자열 매칭시켜(term당
   최대 5개, doc_id 기준 결정적 정렬) 찾아낸 "경계 사례" 후보. **relevance 점수에는 전혀 반영되지
   않고, 오직 "사람이 볼 후보에 포함되느냐"만 결정한다.**
3. **`random`** — `base_seed + crc32(query_id)`로 시드를 고정한 결정적 랜덤 샘플(쿼리당 8개) —
   검색 시스템이 전혀 못 찾은 "명백히 무관한" 문서도 일부 판정 대상에 넣어 hard negative 학습
   재료와 false-negative 점검 기준을 확보

같은 `(query_id, doc_id)`가 여러 채널에서 나오면 `pool_sources_json`에 채널별 근거가 모두
누적된다(사람에게는 안 보여줌 — blind annotation 원칙). 후보가 하나도 없는 쿼리는 없어야 하며,
corpus에 없는 doc_id가 섞이면 즉시 에러.

**출력 파일** (`benchmark_dir` 밑)
- `candidate_pool_internal.csv` — **provenance가 담긴 내부 자료, 절대 애노테이터에게 그대로
  주면 안 됨**(08번이 여기서 relevance 판정용 sheet를 따로 만든다)
- `pool_stats.json` — 이번 라운드 통계(쿼리당 pool 크기 min/median/mean/max, 시스템 수)
- `pool_history.csv` — 라운드별 통계 누적(같은 라운드로 재실행하면 그 라운드 행만 교체)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_active_queries`, `load_config` — 매칭/누적 로직은
  스크립트 내부 구현(전용 src 모듈 없음)

---

## `08_make_full_annotation_sheets.py`

**한 줄 요약**: candidate pool 전체를 실제 relevance 판정용 애노테이션 시트로 바꾼다 — train은
A 혼자, val/test는 A/B 독립 이중 판정.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `benchmark_dir/candidate_pool_internal.csv`, `queries.csv`(status=active만)

**핵심 로직**
무결성 검사: split이 정확히 {train,val,test} 세 종류인지, query_id/pool의 (query_id,doc_id) 쌍
중복이 없는지, 활성 쿼리가 전부 pool에 후보를 갖고 있는지. `judgment_id =
sha256(query_id|doc_id)[:20]`을 이 단계에서 처음 부여한다(이후 09/10번과
`split_completed_annotations.py`가 전부 이 id로 조인).

**A는 train+val+test 전체를 판정한다**(train은 fine-tuning 신호로만 쓰이므로 사람 1명이면
충분하다는 원칙). **B는 val+test만** 판정한다(train은 double-annotation 대상이 아님 — 시간
절약). `stable_shuffle()`이 각 쿼리 내부의 후보 순서를 `seed + annotator` 조합으로 결정적으로
섞어서, A와 B가 같은 순서로 후보를 보지 않게 한다(순서 효과에 의한 편향 감소).

애노테이터가 작업하기 편하도록 **같은 내용을 두 형태로** 낸다: A는 `annotation_A_all.csv`(전체
한 파일)와 `annotation_A_{train,val,test}.csv`(split별) 둘 다, B는 `annotation_B_val_test.csv`와
`annotation_B_{val,test}.csv` 둘 다. 어느 쪽을 채워도 결과는 같다(뒤에서
`split_completed_annotations.py`가 combined 버전을 per-split 버전으로 변환해줌).

**출력 파일** (`benchmark_dir/annotations/full_annotation_v1/` 밑)
`annotation_A_all.csv`, `annotation_A_train.csv`, `annotation_A_val.csv`, `annotation_A_test.csv`,
`annotation_B_val_test.csv`, `annotation_B_val.csv`, `annotation_B_test.csv`,
`annotation_manifest.json`(정책 문서화: train=single/val·test=double+adjudication, test는 학습·
하이퍼파라미터·템플릿 선택 어디에도 쓰면 안 된다는 leakage 정책 포함)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`

---

## `split_completed_annotations.py` *(번호 없는 유틸리티, 08과 09 사이에 위치)*

**한 줄 요약**: 애노테이터가 combined 시트(`annotation_A_all.csv`, `annotation_B_val_test.csv`)로
작업했을 때, 그 결과를 `09_prepare_full_annotations.py`가 요구하는 **5개 split별 완료 파일**로
쪼개준다.

**입력 파일**
- `--a-all`(기본 `completed/annotation_A_all_completed.csv`),
  `--b-val-test`(기본 `completed/annotation_B_val_test_completed.csv`)
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)

**핵심 로직**
왜 필요한가: `08_make_full_annotation_sheets.py`는 애노테이터 편의를 위해 combined 파일도
만들어 두는데(08번 절 참고), `09_prepare_full_annotations.py`는 **각 split을 독립적으로 검증하기
위해** split별 파일만 읽도록 설계돼 있다. 이 스크립트는 단순히 `split` 컬럼 값으로 행을 나눠
저장할 뿐이라 애노테이터가 채운 relevance/uncertain 값은 전혀 바뀌지 않는다 — A 파일은
train/val/test 3개로, B 파일은 val/test 2개로 쪼갠다.

**출력 파일** (`completed/` 밑)
`annotation_A_train_completed.csv`, `annotation_A_val_completed.csv`,
`annotation_A_test_completed.csv`, `annotation_B_val_completed.csv`,
`annotation_B_test_completed.csv` — 이후 `python scripts/09_prepare_full_annotations.py`를 그대로
이어서 실행하면 된다.

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`

---

## `09_prepare_full_annotations.py`

**한 줄 요약**: 완료된 5개 애노테이션 시트를 검증하고, train은 바로 provisional qrels로, val/test는
A/B 비교 후 일치분 자동 확정 + 불일치분을 adjudication 대상으로 분리한다. **val+test 전체의
이중 라벨링 합치도(`agreement_report.json`)도 이 스크립트가 만든다.**

**입력 파일** (`benchmark_dir/annotations/full_annotation_v1/completed/` 밑, 5개 전부 필수)
`annotation_A_train_completed.csv`, `annotation_A_val_completed.csv`,
`annotation_A_test_completed.csv`, `annotation_B_val_completed.csv`,
`annotation_B_test_completed.csv`

**핵심 로직**
각 파일을 로드하며 judgment_id/query_id+doc_id 중복, relevance 값이 {0,1,2,3} 범위인지 검사하고
`uncertain` 컬럼을 boolean으로 정규화한다. 또한 각 파일의 `split` 컬럼이 파일명이 암시하는 split
하나로만 채워져 있는지 확인한다(섞여 있으면 에러).

**Train**: 단일 애노테이터(A)이므로 조정 없이, `relevance`가 있고 `uncertain`이 아닌 행만
"usable_for_training"으로 걸러 그대로 `qrels_train_provisional.csv/.trec`로 저장한다. 제외된
행(결측/uncertain)은 `train_uncertain_excluded.csv`로 따로 남긴다.

**Val/Test**: `pairwise_report()`가 A/B를 judgment_id로 조인해서, 값이 유효한 쌍 중
`relevance_A == relevance_B`면 `exact_agree`로 자동 확정(`final_relevance`에 그 값을 채움), 아니면
`needs_adjudication=True`로 표시한다. 불일치는 심각도로 우선순위를 매긴다:
- **P0_UNCERTAIN_OR_MISSING** — 둘 중 하나라도 uncertain이거나 값이 없음
- **P1_BINARY_THRESHOLD** — 값은 있지만 `(rel≥2)` 여부(관련/무관 판정 자체)가 갈림 —
  binary metric에 직접 영향을 주는 가장 심각한 불일치
- **P2_GRADED_ONLY** — 관련/무관 판정은 같은데 정확한 등급만 다름 — graded nDCG에만 영향
같은 유효 쌍들로 exact/binary agreement, unweighted·quadratic-weighted·binary Cohen's kappa를
split별로 계산한다(val, test 각각).

**추가로(calibration 삭제 후 새로 생긴 책임)**: val_merged + test_merged를 **합쳐서** 이중
라벨링 커버리지(`human_double_annotation_completed_rows / required_rows`)와 exact/binary
agreement, Cohen's kappa(unweighted/quadratic-weighted)를 다시 한번 계산해 `agreement_report.json`
스키마로 만든다. 이 파일은 원래 (지금은 삭제된) calibration 스크립트가 만들던 것과 같은
스키마이며, `12_validate_benchmark.py --stage final`이 그대로 찾아서 읽는다(자세한 배경은
문서 하단 FAQ Q6).

**출력 파일** (`benchmark_dir/annotations/full_annotation_v1/` 밑, `agreement_report.json`만 예외)
- `qrels/provisional_v1/qrels_train_provisional.csv/.trec` — **11번의 `--train-qrels` 기본값과
  동일 경로**
- `analysis/adjudication_val_test_full.csv` — val/test 전체(자동 확정분 + 미확정분)
- `analysis/adjudication_val_test_needed_only.csv` — 사람이 봐야 할 불일치 행만, 우선순위순 정렬.
  **여기에 `final_relevance`를 채운 뒤 `_completed.csv`로 저장하는 게 다음 사람 작업**
- `analysis/qrels_{val,test}_agreed_partial_DO_NOT_SCORE.csv` — 자동 확정분만 모은 진단용 참고
  파일("DO_NOT_SCORE" — 아직 조정 안 된 불완전한 qrels이므로 절대 채점에 쓰면 안 됨)
- `analysis/train_uncertain_excluded.csv`, `analysis/full_annotation_analysis_summary.json`
- **`benchmark_dir/agreement_report.json`**(위 두 폴더보다 한 단계 위, `benchmark/storesearch_ko_v1/`
  바로 밑) — `12_validate_benchmark.py --stage final`이 읽는 파일

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`, `write_trec_qrels`

---

## `10_apply_adjudication_patch.py`

**한 줄 요약**: 3rd adjudicator가 채운 "불일치 건 최종 판정"을 전체 val/test 파일에 병합한다.

**입력 파일**
- `--full`(기본 `analysis/adjudication_val_test_full.csv`, 09번 산출물)
- `--patch`(기본 `analysis/adjudication_val_test_needed_only_completed.csv` — 사람이
  `final_relevance`, `human_adjudication_note`, 필요시 `exclude_from_gold`를 채운 파일)

**핵심 로직**
judgment_id로 patch를 full에 병합하되, **patch에 있는 judgment_id 중 full에 없는 게 있으면
에러**(오타/잘못된 파일 방지). `final_relevance`가 {0,1,2,3} 밖의 값이면 에러. 빈 CSV 셀이
pandas에 의해 float64로 잘못 추론되는 문제를 피하려고 문자열 컬럼은 `astype("string")`, 숫자
컬럼은 `astype("Float64")`로 명시 캐스팅한 뒤 numpy 배열로 대입한다. 마지막에 **"제외되지 않았는데
final_relevance가 여전히 비어있는 행"**(`unresolved_non_excluded`)이 있는지 검사해서 0이 아니면
경고와 함께 해당 행 목록을 보여준다 — 이 숫자가 0이어야 다음 단계(11)가 성공한다.

**출력 파일**
- `--output`(기본 `analysis/adjudication_val_test_full_completed.csv`) — **11번의
  `--adjudication` 기본값과 동일 경로**

**사용하는 src/ 코드**
- 없음(순수 pandas + argparse)

---

## `11_build_qrels.py`

**한 줄 요약**: train(provisional) + val/test(adjudication 완료본)를 합쳐 **최종 공식 qrels**를
만든다 — 이 단계를 통과해야 비로소 "gold"라고 부를 수 있다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `benchmark_dir/queries.csv`(active만)
- `--adjudication`(기본 `analysis/adjudication_val_test_full_completed.csv`, 10번 산출물)
- `--train-qrels`(기본 `qrels/provisional_v1/qrels_train_provisional.csv`, 09번 산출물)

**핵심 로직**
`build_split_qrels()`가 val/test 각각에 대해: `exclude_from_gold`가 Y인 행은 gold에서 완전히
제외(정보 부족 등으로 정당하게 판정 불가한 케이스 — 삭제가 아니라 명시적 제외), 제외되지 않았는데
`final_relevance`가 없는 행이 하나라도 있으면 **즉시 에러**(10번에서 전부 해결됐어야 함). 통과하면
train/val/test를 합쳐 `qrels_all`을 만들고 split을 넘나드는 (query_id,doc_id) 중복이 없는지
마지막으로 한 번 더 검사한다(family/split leakage 방지의 2차 방어선, 1차는 12번).

**출력 파일** (`benchmark_dir` 바로 밑, 서브폴더 없음 — "이제 provisional이 아니라 최종"이라는
신호)
- `qrels_train.csv/.trec`, `qrels_val.csv/.trec`, `qrels_test.csv/.trec`, `qrels.csv/.trec`(전체)
- `benchmark_manifest.json` — split별 등급 분포/쿼리 수, **모든 산출 파일의 sha256** — "이 평가에
  쓰인 벤치마크가 정확히 어떤 버전인지"를 나중에 재현/인용할 수 있게 하는 핵심 지문
- (`--freeze` 플래그를 주면) `benchmark_dir/frozen/`에 이 산출물 + config + guideline을 통째로
  복사해 불변 스냅샷으로 만든다. `frozen/`이 이미 있으면 실행을 거부한다(동결된 벤치마크를
  실수로 덮어쓰지 못하게)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`, `sha256_file`, `write_trec_qrels`

---

## `12_validate_benchmark.py`

**한 줄 요약**: 지금까지 나온 산출물 전체(쿼리/pool/qrels)의 무결성을 점검하는 게이트. `pilot`은
구조적 검증만, `final`은 config가 정한 최소 기준까지 검사한다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `queries.csv`, corpus parquet, `candidate_pool_internal.csv`(있으면), `qrels.csv`(있으면),
  `agreement_report.json`(있으면 — **09번(`09_prepare_full_annotations.py`)이 만드는 파일**.
  이 스크립트는 파일 스키마만 볼 뿐 누가 만들었는지는 신경 쓰지 않는다 — 전에는 이제 삭제된
  calibration 스크립트가 만들었고, 지금은 09번이 만든다)

**핵심 로직**
공통 검사: query_id 중복, 정규화된 쿼리 텍스트 중복, **family가 두 split에 걸치는지**
(query-family 단위 split이므로 이게 걸리면 leakage), corpus doc_id 유일성. pool이 있으면 pool
크기 통계 + `min_pool_size_warn`(=60) 미만이면 경고 + pool에 corpus에 없는 doc_id가 있으면 에러.
qrels가 있으면 중복 쌍/등급 범위/미지의 query_id·doc_id 검사, `binary_threshold`(=2) 이상 문서가
하나도 없는 쿼리를 찾아낸다.

`--stage final`에서만 추가로: 전체 쿼리 수 ≥ `min_total_queries_final`(=120), test 쿼리 수 ≥
`min_test_queries_final`(=50), **pool 시스템 다양성** ≥ `min_pool_systems_final`(현재 3 —
lexical 3개로 확정, 원래는 dense pooling까지 염두에 둔 6이었음), `agreement_report.json`이
존재하고 그 안의 `double_annotation_coverage` ≥ `target_double_annotation_coverage`(=1.0).

**출력 파일**
- `validation_{stage}.json` — `errors`가 비어있어야 `valid: true`. 에러가 있으면 `SystemExit(1)`로
  종료(CI/스크립트 체이닝에서 실패로 감지 가능)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_active_queries`, `load_config`

---

## `13_evaluate_run.py`

**한 줄 요약**: **공식 evaluator, 단 하나** — 모든 모델·모든 실험의 run.csv가 반드시 이 스크립트를
거쳐야 점수가 나온다. 14/15번은 이 스크립트를 서브프로세스로 호출할 뿐 채점 로직을 복제하지 않는다.

**입력 파일**
- `--qrels`(기본 `benchmark/storesearch_ko_v1/qrels_val.trec`): `.trec` 또는 `.csv`
- `--run`(필수): `.trec` 또는 `.csv`(`query_id,doc_id,rank,score[,system]`)
- `--tag`(필수): 결과 파일 이름에 쓰이는 실험 식별자
- `--compare-run`(선택): baseline run과 페어 비교

**핵심 로직**
파일 맨 위에 **Python 3.12+ 호환 shim**이 있다: `ir_measures.util.parse_measure()`가 내부적으로
`isinstance(node, ast.Num)`을 쓰는데 `ast.Num`이 Python 3.12에서 제거됐다(3.8부터 `ast.Constant`로
통합, deprecated 거쳐 결국 삭제). `hasattr(ast, "Num")`이 거짓이면 `ir_measures.util._ast_to_value`
를 `ast.Constant` 기반 구현으로 통째로 교체한 뒤에야 `ir_measures`를 import한다 — 프로젝트를
Python<3.12에 묶어두지 않기 위한 방어적 패치.

`.trec` 로딩은 파일을 **직접 `encoding="utf-8"`로 열어서** `ir_measures.read_trec_qrels`/
`read_trec_run`에 파일 객체로 넘긴다(경로 문자열을 그대로 넘기면 `ir_measures`가 OS 로케일
인코딩— 한글 Windows면 cp949 —으로 열어버려서, `q_치킨_01`처럼 query_id에 한글이 들어간 현재
쿼리셋에서 `UnicodeDecodeError`가 난다).

`METRIC_SPECS`가 공식 지표 8개를 고정한다: **nDCG@10**(PRIMARY_METRIC, graded 0~3 그대로 사용),
Precision@10/MRR@100/Recall@50/Recall@100/Bpref(전부 `rel=2` 이상만 관련으로 보는 binary 버전),
Judged@10/Judged@100(상위 k 중 실제 판정된 문서 비율). 계산은 전부 `ir_measures.calc_aggregate`/
`iter_calc`에 위임 — 직접 재구현하지 않는다. 쿼리 단위 값에 **비모수 부트스트랩 95% CI**(기본
10000회 리샘플)를 씌우고, `--compare-run`을 주면 **paired permutation test**로 두 시스템의 지표
차이가 유의한지 검정한다(여러 모델을 동시에 비교할 땐 p-value에 Holm 보정을 하라는 안내 포함).

**출력 파일** (`--output-dir` 기본 `artifacts/evaluation/storesearch_ko_v1/`)
- `{tag}_per_query.csv` — 쿼리별 지표값
- `{tag}_evaluation.json` — aggregate 지표, bootstrap CI, run 무결성 검사 결과, (있으면) baseline
  대비 비교 결과 — **14/15번과 model_manifest 갱신 로직이 이 JSON의 `aggregate` 필드를 다시 읽는다**

**사용하는 src/ 코드**
- 없음(순수 `ir_measures`/`numpy`/`pandas` — src 모듈 의존 없음)

---

## `14_run_model_eval.py`

**한 줄 요약**: 모델 하나를 인코딩→검색→평가까지 한 번에 돌린다. zero-shot 모델(HF Hub id)과
fine-tuned 모델(로컬 경로)을 완전히 같은 코드로 처리한다 — 그래서 이름에 "zero_shot"이 없다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `--model-config`: `configs/models/*.yaml` 하나(`model_id`가 HF Hub id면 zero-shot, 로컬
  디렉터리 경로면 fine-tuned 체크포인트 — `docs/TRAINING.md` 참고). `--dummy`를 주면 모델 설정
  없이 `RandomEncoder`로 배관만 검증
- corpus, active queries 중 `--split`(기본 val) 필터링분

**핵심 로직**
`build_encoder()`가 `--dummy`면 `RandomEncoder`, 아니면 `SentenceTransformerEncoder.from_yaml()`을
만든다. `--template`(기본 `t1_minimal`)에 대응하는 컬럼으로 corpus를 인코딩하고, 쿼리를
인코딩(`SentenceTransformerEncoder`는 query에만 `query_prompt_name`을 적용 — 모델별 instruction
prompt 차이를 여기서 흡수), `ExactCosineSearch`로 top-k(기본 100) run을 만들어 `run.csv`로 저장.
`--skip-evaluate`가 없으면 `13_evaluate_run.py`를 서브프로세스로 호출한다.

**평가 후 model_manifest 자동 갱신**: 평가가 끝나면, `--model-config`의 `model_id`가 **로컬
디렉터리**를 가리키는지 확인한다. 맞으면(=fine-tuned 체크포인트) 방금 13번이 만든
`{eval_tag}_evaluation.json`을 다시 읽어서 `aggregate` 지표를 그 체크포인트 폴더의
`model_manifest.json`의 `evaluations` 리스트에 이어붙인다(`append_model_manifest_evaluation`).
`model_manifest.json`이 없으면(=zero-shot HF Hub 모델) 조용히 아무 일도 하지 않는다.

**출력 파일**
- `results/model_eval/{tag}/run_{template}_{split}.csv`
- (13번을 통해) `artifacts/evaluation/storesearch_ko_v1/{tag}_{split}_evaluation.json` 등
- (fine-tuned 로컬 모델일 때만) `{model_id}/model_manifest.json`의 `evaluations` 갱신

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_active_queries`, `load_config`,
  `append_model_manifest_evaluation`
- `store_search_ai.models.random_encoder.RandomEncoder`(`--dummy`) 또는
  `store_search_ai.models.sentence_transformer_encoder.SentenceTransformerEncoder`
- `store_search_ai.retrieval.exact_search.ExactCosineSearch`

---

## `15_score_model_runs.py`

**한 줄 요약**: `results/model_eval/` 밑에 쌓인 여러 모델×템플릿 run을 한 번에 채점해서 리더보드
하나로 합친다. Colab(zero-shot/fine-tuned 무관)에서 만든 run과 로컬에서 만든 run을 구분하지 않는다.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`)
- `--results-dir`(기본 `results/model_eval`) 밑 `*/run_*_{split}.csv` 전부

**핵심 로직**
`RUN_NAME_RE`(`run_(?P<template>.+)_(train|val|test)\.csv`)로 파일명에서 template을 역파싱하고,
상위 폴더명을 tag로 쓴다. `(tag, template)` 조합마다 `13_evaluate_run.py`를 서브프로세스로
호출해서(qrels는 모두 같은 `qrels_{split}.trec`) 그 결과 JSON의 `aggregate`만 뽑아 한 행으로
쌓는다. 전부 모은 뒤 `nDCG@10` 기준 내림차순으로 정렬한다.

**출력 파일**
- `--output`(기본 `results/model_eval/leaderboard_{split}.csv`)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_config`

---

## `prepare_finetune_dataset.py` *(번호 없는 유틸리티, 15번 이후 — fine-tuning 데이터 준비)*

**한 줄 요약**: `qrels_train`(+ corpus, queries.csv)으로부터 fine-tuning용 (query, positive,
negatives) 학습쌍 jsonl을 만든다. Colab 학습(`colab/run_finetune_*.py`)에 넘길 최종 산출물.

**입력 파일**
- `--config`(기본 `configs/benchmark/storesearch_ko_v1.yaml`) → `corpus_path`, `benchmark_dir`,
  `evaluation.binary_relevance_threshold`
- `--qrels`(생략 시 자동 탐색): `benchmark_dir/qrels_train.csv`(11번의 최종본)가 있으면 그것,
  없으면 `qrels/provisional_v1/qrels_train_provisional.csv`(09번의 provisional본) — **즉 val/test
  adjudication을 기다리지 않고 train 애노테이션만 끝나도 바로 fine-tuning 데이터를 만들 수 있다**
- `queries.csv`(train split만), corpus의 `--template`(기본 `t1_minimal`) 컬럼

**핵심 로직**
쿼리별로 qrels를 그룹핑해서: **positive** = `relevance >= binary_relevance_threshold`(기본 2)인
문서 중 첫 번째, **negatives** = 같은 쿼리의 같은 pool에서 그 미만인 문서를 최대
`--max-negatives`(기본 8)개. negative를 고를 때 `relevance=1`(경계 사례)을 `relevance=0`보다
먼저 정렬해서 우선 채운다 — 무작위 negative보다 "어휘적으로는 비슷해 보이지만 실제로는 관련
없는" 진짜 어려운 negative를 우선하는 것으로, GPL/E5/BGE 계열 논문의 hard negative mining과
같은 발상이다. pooling(06~07)이 이미 그런 후보를 모아 놨고 train qrels가 그 전체 pool에 대한
사람 판정이므로 추가 검색 없이 바로 재사용된다. positive가 하나도 없는 쿼리(=pool 전체가 낮은
relevance)는 학습쌍을 만들 수 없으므로 제외하고 개수를 로그에 남긴다.

출력 스키마는 프레임워크 중립적이다(`{"query_id","query","positive","negatives":[...]}"`) —
ms-swift는 `positive→response`, `negatives→rejected_response`로 매핑해서 쓰고,
sentence-transformers는 `InputExample(texts=[query, positive, *negatives])`로 그대로 쓴다.

**출력 파일**
- `--output`(기본 `data/finetune/train_pairs.jsonl`) — qrels_train + corpus + queries.csv로부터
  결정적으로 재생성되는 파생 파일(train qrels가 갱신되면 다시 돌리면 됨)

**사용하는 src/ 코드**
- `store_search_ai.pipeline.common.load_active_queries`, `load_config`

---

## 자주 나올 질문

**Q1. train qrels랑 val/test qrels는 왜 만드는 방식이 다른가요?**
→ 08번 절 + 09번 절. train은 fine-tuning 학습 신호로만 쓰이고 모델 성능을 "보고"하는 데는 안
쓰이므로 애노테이터 1명(A)의 단일 판정으로 충분하다는 게 팀 정책(`08_make_full_annotation_sheets.py`
의 `annotation_manifest.json` `data_leakage_policy`에 명시). val/test는 실제로 발표/의사결정에
쓰이는 gold라서 A/B 독립 이중 판정 + 3rd adjudicator 조정을 반드시 거친다.

**Q2. 왜 corpus 21만 건을 전부 판정하지 않고 pooling을 쓰나요?**
→ 07번 절. 쿼리 수 × 21만 건을 전부 사람이 보는 건 애초에 불가능하다. TREC 스타일 pooling은
"여러 독립적인 검색 방법이 관련 있어 보인다고 지목한 문서의 합집합"만 사람에게 보여줘서 판정을
현실적인 규모로 줄인다 — 그 대신 시스템이 충분히 다양해야(12번의 `min_pool_systems_final`) 어떤
검색 방법으로도 못 찾은 진짜 관련 문서가 통째로 빠지는 위험을 줄일 수 있다.

**Q3. pooling 시스템끼리 서로 다른 문서를 찾으면 어떻게 되나요?**
→ 07번 절. 교집합이 아니라 **합집합**이다. 한 시스템이라도 어떤 문서를 지목하면 그 문서는 사람이
판정할 pool에 들어간다(`pool_sources_json`에 어떤 채널이 찾았는지 기록만 되고, 애노테이터에게는
안 보여줌 — blind annotation). 반대로 세 시스템 다 못 찾은 문서는 random 채널로 뽑히지 않는 한
아예 판정 대상이 되지 못한다.

**Q4. T1/T2/T3 템플릿이 뭐고 왜 T1이 공식인가요?**
→ 02/04번 절. 코퍼스에는 세 검색 텍스트 표현(T1=가맹점명+취급품목, T2=+시장명, T3=+시장유형)이
전부 저장되지만, `docs/PIPELINE.md`가 T1을 공식 document representation으로 못 박았다. 실제
zero-shot 리더보드에서도(`14_run_model_eval.py`로 여러 모델 비교) T1이 T2보다 항상 nDCG@10이
높게 나와 실증적으로도 뒷받침된다.

**Q5. relevance 등급(0~3)이 실제 지표에는 어떻게 반영되나요?**
→ 05번 절(guideline) + 13번 절. graded 0~3은 nDCG@10 계산에 그대로 쓰이고, 나머지 공식 지표
(Precision/MRR/Recall/Bpref)는 전부 `binary_threshold=2` 기준으로 이분화해서(2 이상만 "관련")
계산한다(`configs/benchmark/storesearch_ko_v1.yaml`의 `relevance.binary_threshold` /
`13_evaluate_run.py`의 `BINARY_THRESHOLD` 상수).

**Q6. calibration 단계(옛 08~10번)는 어디 갔나요?**
→ 삭제했다. 애노테이터 간 사전 신뢰도 보정(본 애노테이션 전에 소수 family로 미리 합치도를
확인하는 단계)이었는데, 실제로는 한 번도 쓰이지 않고 바로 본 애노테이션(현재 08번)으로
진행했다. 또한 하드코딩된 family 목록(`CALIBRATION_FAMILIES` 등)이 예전 영문 family 이름
그대로라 지금 한글 이름 체계인 `query_families_v1.yaml`로는 실행 자체가 안 되는 상태였다.
필요하면 git 이력(calibration 관련 커밋)에서 세 스크립트를 복원할 수 있지만, family 목록은
현재 yaml 기준으로 다시 써야 한다. calibration이 만들던 `agreement_report.json`
(`12_validate_benchmark.py --stage final`이 요구하는 파일)은 이제 **09번
(`09_prepare_full_annotations.py`)이 본 애노테이션의 val+test 결과로부터 직접 계산해서
만든다** — 별도 calibration 라운드 없이도 이 요구사항이 채워진다.

**Q7. 최종 qrels가 나온 뒤 모델 평가 전에 뭘 더 확인하나요?**
→ 12번 절. `--stage final`이 쿼리/테스트 수 하한, pool 시스템 다양성, 이중 판정 커버리지를
전부 통과해야("valid": true) 그 qrels가 "확정"됐다고 볼 수 있다. 통과 못 하면 `SystemExit(1)`로
실패하므로 CI/스크립트에서 바로 감지된다.

**Q8. fine-tuning한 모델을 나중에 서비스에 연결할 때 뭘 봐야 하나요?**
→ 14번 절 + `store_search_ai.pipeline.common.write_model_manifest`/
`append_model_manifest_evaluation`. 학습 스크립트(`colab/run_finetune_*.py`)가 체크포인트 폴더에
`model_manifest.json`(base 모델, 학습 데이터 sha256, 하이퍼파라미터)을 남기고,
`14_run_model_eval.py`로 평가할 때마다 그 안의 `evaluations` 리스트에 val/test 점수가 자동으로
쌓인다. 어떤 체크포인트를 배포할지 고를 때 이 파일 하나만 보면 된다(`docs/TRAINING.md` 4절).

**Q9. 쿼리 원본은 어디서 오고, fine-tuning 데이터는 어떻게 만드나요?**
→ `import_queryset_xlsx.py` 절 + `prepare_finetune_dataset.py` 절. 둘 다 01~15 실행 순서에
속하지 않는 번호 없는 유틸리티지만 실제 워크플로우에서는 필수다: 전자는 `queryset_final.xlsx`
(팀이 편집)를 `query_families_v1.yaml`(05번이 읽는 파일)로 바꾸고, 후자는 09/11번이 만든
train qrels를 Colab 학습(`docs/TRAINING.md`)이 바로 쓸 수 있는 jsonl로 바꾼다.
