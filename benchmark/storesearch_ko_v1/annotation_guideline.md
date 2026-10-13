# StoreSearch-KO v1 Annotation Guideline

<!-- 이 파일은 src/store_search_ai/data/benchmark_init.py의 GUIDELINE 문자열에서 생성됩니다.
     내용을 고치려면 이 .md가 아니라 그 파일을 수정한 뒤 scripts/05_init_benchmark.py를 다시 실행하세요. -->

_v1.1 (2026-09-22) — 실제 데이터에서 확인된 경계 사례(복합 업종, 편의점/마트, 저정보 표현,
오탈자)를 반영해 갱신._

## 적용 범위
이 가이드라인은 train/val/test 모두에 적용됩니다. train은 애노테이터 1명의 단일 라벨링
(`08_make_full_annotation_sheets.py`), val/test는 사람 2명의 이중 라벨링 + adjudication을
거쳐 확정됩니다(`docs/PIPELINE.md` 4~5절). val/test는 실제 모델 성능을 "보고"하는 gold이므로
반드시 두 사람이 서로의 판정을 모르는 상태로 독립 판정해야 하고, train은 fine-tuning 학습
신호로만 쓰이므로 단일 판정으로 진행한다.

## 목적
사용자 Query에 대해 각 매장이 검색 결과로 얼마나 적절한지 0~3의 graded relevance로 평가한다.
Retrieval system은 `query`만 입력으로 받는다. `intent_definition`은 평가자에게 의도를 명확히
하기 위한 topic 설명이다. `query_families_v1.yaml`의 `positive_terms`/`boundary_terms`는
pooling 단계에서 후보를 빠짐없이 모으기 위한 것일 뿐 relevance 등급을 지정하는 값이 아니다 —
같은 family의 positive_terms에 속한 후보라도 최종 등급은 항상 아래 기준으로 개별 판단한다.

## 점수
### 3 — Directly Relevant
사용자의 핵심 검색 의도를 직접 만족한다.
- `통닭` → 치킨전문점
- `고기 파는 곳` → 정육점
- `머리 자르는 곳` → 두발미용/미용실

### 2 — Relevant
좋은 검색 결과에 포함될 수 있으나 직접적인 핵심 의도보다 한 단계 넓거나 인접하다.
- `통닭` → 닭강정
- `빵집` → 제과·케이크 전문점(실제 빵 판매가 합리적으로 예상되는 경우)

### 1 — Related but Unsatisfactory
주제상 연관은 있으나 사용자의 검색 성공으로 보기 어렵다.
- `통닭` → 생닭 판매
- `고기 파는 곳` → 삼겹살 음식점
- `머리 자르는 곳` → 피부미용

### 0 — Not Relevant
사용자의 검색 의도를 만족하지 않는다.

**1과 2를 가르는 일반 기준**: 그 매장이 검색자의 핵심 니즈를 대체 가능하게 충족시킬 수 있으면
2, 주제만 겹치고 핵심 니즈 자체는 충족되지 않으면 1로 본다. (닭강정 전문점은 "치킨을 먹고
싶다"는 니즈를 대체 충족하므로 2, 생닭 판매점은 "조리된 치킨을 먹고 싶다"는 니즈를 충족하지
못하므로 1.)

## Binary relevance
Precision/Recall/RR/Bpref 등 binary metric에서는 `relevance >= 2`만 relevant로 간주한다.
nDCG에서는 0/1/2/3 전체 graded label을 사용한다.

## 판단 원칙
1. `store_name`과 `item_text`를 가장 중요한 근거로 본다.
2. `intent_definition`은 Query의 의도 경계를 이해하기 위해 사용한다.
3. `market_name`은 보조 정보일 뿐, 시장명만으로 relevance를 올리지 않는다.
4. Query에 없는 지역·결제수단 조건을 임의로 가정하지 않는다.
5. 판매점과 음식점, 서비스와 상품 판매를 구분한다.
6. 정보가 부족하여 판단이 불가능하면 `uncertain=Y`, relevance는 비워둔다. 정보는 충분하나
   인접 등급(예: 1 vs 2) 사이에서 판단이 갈리는 경우는 이와 다른 상황이므로 `uncertain`으로
   묶지 말고, 점수는 확정하되 `annotator_note`에 어느 등급 사이에서 고민했는지 짧게 남긴다
   (adjudication 시 불일치 원인을 구분하기 위함).
7. 다른 평가자의 점수나 candidate retrieval source/rank/score를 보지 않고 독립적으로 판정한다.
8. 같은 기준을 모든 Query에 일관되게 적용한다.

## 경계 사례
실제 데이터 검토에서 아래 다섯 가지 상황이 반복적으로 등장했고, 위 원칙만으로는 해석이 갈릴
수 있어 별도로 정리한다.

### 복합 업종 매장
`item_text`에 업종이 여러 개 나열된 경우(예: `화초및식물소매업 제과점업`), 나열된 업종 중
query 의도와 정확히 일치하는 업종이 하나라도 있으면 그 업종 기준으로 그대로 점수를 준다.
다른 업종이 섞여 있다고 감점하지 않는다.
- 예: "빵집" query + `item_text: 화초및식물소매업 제과점업` → 3점 (꽃도 같이 파는 것은 이
  매장이 실제로 빵을 판다는 사실을 훼손하지 않는다)

### 편의점 / 마트 (포괄적 업종)
구체적 상품 query에 편의점·마트류(`item_text`가 "편의점", "체인화 편의점" 등)가 후보로 나오는
경우, 그 상품이 편의점에서 통상 취급하는 일반 생활용품(가공식품·음료·생활잡화·문구·담배 등)이면
2점, 전문/특수 품목(가구·가전·전문 공구 등)이면 0점으로 처리한다.
> 잠정 기준. "일반 생활용품"의 경계가 넓게 해석될 수 있어, family 2~3개로 소규모 파일럿을
> 돌려 A/B 불일치가 여기 몰리는지 먼저 확인하고 필요하면 품목 화이트리스트를 추가한다.

### `item_text` 결측 또는 저정보 표현
`item_text`가 없거나 "서비스", "판매", "기타"처럼 정보량이 거의 없으면 원칙 1(매장명 우선)을
적극 적용해 `store_name`만으로 판정한다. `store_name`에도 단서가 없으면 `uncertain=Y`.
- 예: `store_name: 명품노래연습장 / item_text: 서비스` → "노래연습장" query에 매장명 근거로
  3점
- 예: `store_name: 프롬핸즈 / item_text: (결측)` → 매장명만으로 판단 불가 → uncertain

### `store_name`과 `item_text`의 구체성이 다를 때
둘 중 더 구체적이고 직접적인 정보를 우선한다(원칙 1과 동일한 결론이지만 자주 나와 명시한다).
- 예: `store_name: 부대찌개 / item_text: 음식점` → "부대찌개" query에 3점 (`item_text`가
  포괄적이어도 `store_name`이 더 구체적인 근거)

### 오탈자 / 깨진 문자
알아볼 수 있는 범위 내에서는 정상 판정하고, 오탈자를 이유로 감점하지 않는다. 전혀 해독
불가능한 경우만 `uncertain=Y`.
- 예: `item_text: ㅓ미용`("미용" 오타) → "미용실" query에 정상적으로 3점

## Blind annotation
실제 annotation sheet에는 pooling system, hint, retrieval rank, retrieval score를 노출하지 않는다.

## AI 보조 사용
AI는 사례 검토·판정 근거 정리·adjudication 보조로 사용할 수 있고, 애노테이터 본인이 자신의
A/B 라벨에 AI 초안을 참고하는 것도 허용한다 — 다만 최종 점수는 반드시 애노테이터 본인이
확정해야 하며, AI의 판정 자체를 val/test의 독립적인 인간 평가자(A/B) 점수로 계산하지 않는다.
논문에서 human agreement를 보고하려면 val/test의 A/B는 서로 독립적인 인간 평가자여야 한다.
