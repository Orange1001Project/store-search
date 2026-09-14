# StoreSearch-KO v1 Annotation Guideline

## 적용 범위
이 가이드라인은 train/val/test 모두에 적용됩니다. train은 애노테이터 1명의 단일 라벨링
(`08_make_full_annotation_sheets.py`), val/test는 사람 2명의 이중 라벨링 + adjudication을
거쳐 확정됩니다(`docs/PIPELINE.md` 4~5절).

## 목적
사용자 Query에 대해 각 매장이 검색 결과로 얼마나 적절한지 0~3의 graded relevance로 평가한다.
Retrieval system은 `query`만 입력으로 받는다. `intent_definition`은 평가자에게 의도를 명확히 하기 위한 topic 설명이다.

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

## Binary relevance
Precision/Recall/RR/Bpref 등 binary metric에서는 `relevance >= 2`만 relevant로 간주한다.
nDCG에서는 0/1/2/3 전체 graded label을 사용한다.

## 판단 원칙
1. `store_name`과 `item_text`를 가장 중요한 근거로 본다.
2. `intent_definition`은 Query의 의도 경계를 이해하기 위해 사용한다.
3. `market_name`은 보조 정보일 뿐, 시장명만으로 relevance를 올리지 않는다.
4. Query에 없는 지역·결제수단 조건을 임의로 가정하지 않는다.
5. 판매점과 음식점, 서비스와 상품 판매를 구분한다.
6. 정보가 부족하여 판단이 불가능하면 `uncertain=Y`, relevance는 비워둔다.
7. 다른 평가자의 점수나 candidate retrieval source/rank/score를 보지 않고 독립적으로 판정한다.
8. 같은 기준을 모든 Query에 일관되게 적용한다.

## Blind annotation
실제 annotation sheet에는 pooling system, hint, retrieval rank, retrieval score를 노출하지 않는다.

## AI 보조 사용
AI는 사례 검토·판정 근거 정리·adjudication 보조로 사용할 수 있으나, AI 판정을 독립적인 인간 평가자 점수로 계산하지 않는다.
논문에서 human agreement를 보고하려면 val/test의 A/B는 서로 독립적인 인간 평가자여야 한다.
