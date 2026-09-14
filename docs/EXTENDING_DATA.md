# 데이터 확장 가이드

## 1. Raw 데이터를 새 파일로 교체하기

`configs/data/default.yaml`이 raw xlsx를 읽는 방식을 정의합니다.

```yaml
dataset_version: stores_v003

excel:
  region_source: address
  sheets:
    Sheet1: {}

region_aliases:
  서울특별시: 서울특별시
  서울: 서울특별시
  ...
```

- **행(매장)만 늘어나는 경우** (같은 시트에 행이 추가됨): 새 xlsx 파일을 `data/raw/`에 새 파일명으로
  추가하고(기존 파일은 그대로 둡니다 — raw는 수정하지 않습니다), `dataset_version`을 올린 뒤
  `--input`으로 새 파일 경로를 넘기면 됩니다. 컬럼 헤더(`가맹점명`, `사업자번호`, `주소`, `LAT`, `LOT`,
  `법정동코드`, `시장분류코드`, `시장명`, `취급품목`, `카드결제여부`, `모바일결제여부`)가 기존과 동일해야
  `column_map`이 그대로 맞습니다. `가맹점번호`, `No.`(행번호) 컬럼은 없어도 됩니다(옵션).
- **지역(시도) 판별**: 전국 데이터는 시트가 하나뿐이라 시트명으로 지역을 구분할 수 없으므로, **주소
  첫 토큰(시도)을 `region_aliases`로 정규화**해서 `source_region`을 만듭니다
  (`src/store_search_ai/data/region.py::normalize_region`). alias 테이블에 없는 표기가 나오면
  `source_region=None`, `source_region_status="UNMAPPED"`로 조용히 통과합니다(파이프라인이 죽지
  않음) — 새로운 약칭/오탈자가 보이면 `region_aliases`에 한 줄 추가하세요.
  - 과거처럼 지역별로 시트가 나뉜 파일을 다시 쓰려면, 해당 시트 아래에
    `source_region: <값>`을 직접 적으면 그 시트는 주소 파싱 대신 고정값을 씁니다(레거시 호환).
- 컬럼 이름이 바뀌었다면 `column_map`도 함께 수정해야 합니다. `required_raw_columns`에 있는 컬럼이
  없으면 `02_preprocess_data.py`가 즉시 에러를 냅니다(의도된 동작 — 결측 스키마를 조용히 통과시키지 않음).

교체 후 실행 순서는 그대로입니다:

```bash
python scripts/01_profile_data.py --input data/raw/<새파일>.xlsx
python scripts/02_preprocess_data.py --input data/raw/<새파일>.xlsx
python scripts/03_analyze_items.py
python scripts/04_build_corpus.py
```

**store_id는 append-only 레지스트리(`data/registry/store_registry.parquet`)를 통해 발급됩니다.** 기존
매장의 `entity_fingerprint`(사업자번호+가맹점명+주소 해시)가 그대로면 같은 `store_id`가 재사용되고,
신규 매장에는 새 UUID가 발급됩니다. 즉 데이터를 늘려도 **기존 매장의 store_id/doc_id는 바뀌지
않습니다** — 이미 만들어둔 qrels(query_id, doc_id 매핑)가 깨지지 않는다는 뜻입니다. 단, 레지스트리
파일을 지우고 재실행하면 전체 store_id가 새로 발급되므로 지우면 안 됩니다.

`dataset_version`(전처리 산출물 버전)과 `corpus_version`(`configs/benchmark/storesearch_ko_v1.yaml`,
corpus 산출물 버전)은 별도로 관리됩니다. 데이터가 바뀌면 최소 `dataset_version`을 올리고, 그 데이터로
만든 corpus가 이전과 스키마/내용이 다르면 `corpus_version`도 올리세요. 파일 경로는 두 버전 문자열에서
자동으로 파생되므로 스크립트를 고칠 필요는 없습니다.

## 2. Query family 정의하기

**원본은 `data/query/queryset_final.xlsx`입니다** (팀이 통합질의/패밀리목록 시트로 작성). 이 xlsx를
`scripts/import_queryset_xlsx.py`가 읽어 `configs/benchmark/query_families_v1.yaml`을 생성하고,
`05_init_benchmark.py`는 그 yaml만 읽어 `queries.csv`를 만듭니다. **즉 실제 편집 대상은 xlsx이고,
yaml은 생성된 산출물입니다** — yaml을 직접 손으로 고쳐도 동작은 하지만, 다음에 누군가
`import_queryset_xlsx.py`를 다시 돌리면 그 수정은 덮어써집니다.

새 질의를 추가/수정하려면:

```bash
# 1. data/query/queryset_final.xlsx의 "통합질의" 시트에 행 추가(질의/패밀리/대분류/유형/함정 등),
#    새 family라면 "패밀리목록" 시트에도 한 줄 추가(패밀리/대분류/우선순위 등)
# 2. 변환 + 재검증
python scripts/import_queryset_xlsx.py
python scripts/05_init_benchmark.py
python scripts/12_validate_benchmark.py --stage pilot
```

`import_queryset_xlsx.py`가 하는 일(스크립트 상단 docstring에 상세 설명):
- family당 최소 variant 개수 제한 없음(팀 결정 — 548개 질의 전부 유지)
- 기존 yaml에 이미 있는 family 이름은 **split을 그대로 물려받음**(재실행해도 train/val/test가 안 흔들림).
  완전히 새로운 family만 대분류별 균형 + 무작위로 새 split을 배정
- `intent_definition`은 "{대분류} 중 '{family}'을(를) 판매·제공하는 매장" 형태로 초안만 자동 생성 —
  애노테이터에게 실제로 보여줄 문구이므로 **사람이 검토·수정해야 함**
- `positive_terms`/`boundary_terms`는 통합질의 시트의 T1/T2 질의 텍스트와 `함정` 컬럼에서 뽑음(둘 다
  pooling 후보 발굴에만 쓰이고 relevance 판정에는 영향 없음)
- xlsx 병합 과정에서 패밀리가 잘못 배정된 게 확인된 행은 `RECLASSIFY_QUERIES` 딕셔너리에서 정정함
  (원본유형 태그 기반 판단 — 새로 발견되는 오분류가 있으면 이 딕셔너리에 추가)

yaml이 생성하는 각 family의 구조는 다음과 같습니다(참고용 — 직접 쓸 필요는 없음):

```yaml
- family: chicken              # family 이름 (영문, snake_case, 전체 파일 내에서 유일해야 함)
  split: train                 # train / val / test 중 하나. 같은 family가 두 split에 걸치면 안 됨(leakage 방지, 12_validate_benchmark.py가 검사)
  intent_definition: 조리된 치킨·통닭류를 판매하는 음식점   # 애노테이터에게 보여줄 의도 설명 (모델 입력 아님)
  positive_terms: [치킨, 통닭, 치킨전문점, 닭강정]          # pooling 시 targeted term-match 채널(경계 사례 발굴용) — relevance는 사람이 직접 판정
  boundary_terms: [생닭, 닭고기, 육계]                     # 경계 사례 pooling 채널 — relevance는 사람이 직접 판정
  queries:                     # 이 family에 속한 실제 query variant 목록. 최소 1개 필요(3개 이상 권장)
    - type: exact
      text: 치킨
    - type: synonym
      text: 통닭
    - type: paraphrase
      text: 닭튀김 파는 곳
    - type: colloquial
      text: 치킨 먹을 데
```

**주의**: `positive_terms`/`boundary_terms`는 pooling 후보 발굴(targeted term-match 채널, 경계 사례
채널)에만 쓰입니다. train/val/test 모두 relevance는 **사람이 직접 판정**합니다(`docs/PIPELINE.md`
4~5절) — 이 두 필드는 relevance 값 자체에는 영향을 주지 않지만, 후보 pool의 구성(무엇이 애노테이터
앞에 보이는지)에는 영향을 주므로 너무 느슨하거나 너무 좁은 term을 넣으면 pool 품질이 떨어집니다.

`import_queryset_xlsx.py`(및 `05_init_benchmark.py`)가 강제하는 제약:

1. `family` 이름이 파일 전체에서 겹치지 않아야 함 (겹치면 `05_init_benchmark.py`가 에러)
2. `split`은 train/val/test 중 하나 — **한 family는 하나의 split에만 속함** (같은 의도의 query를 여러
   split에 나눠 넣지 않는 것이 원칙; leakage 방지)
3. `queries`는 최소 1개 필요(3개 이상 권장 — 표기·동의어·구어체 등 다양성이 있어야 pooling 품질이 좋음)
4. 같은 query 텍스트(공백 정규화 + casefold 기준)가 파일 전체에서 중복되면 안 됨 — 중복 시 에러
5. `query_id`는 `q_{family}_{순번:02d}` 형식으로 `05_init_benchmark.py`가 자동 생성

**주의**: query family를 추가/변경하면 pooling(06~07)부터 다시 실행해야 하고, 새로 추가되거나 바뀐
query는 train/val/test 가릴 것 없이 애노테이션이 전혀 안 되어 있는 상태이므로 `docs/PIPELINE.md` 4~5절
(본 애노테이션 → adjudication)을 사람이 다시 거쳐야 qrels에 반영됩니다. 변경 전 family의 기존 완료
라벨은 그대로 재사용되고, 새/변경 query만 다시 라벨링하면 됩니다.
