"""`query_families_v1.yaml`(`import_queryset_xlsx.py`가 생성하는 파일)로부터 `queries.csv`를
생성하는 로직.

scripts/05_init_benchmark.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심 로직
전체 (docs/PIPELINE_CODE_REFERENCE.md `05_init_benchmark.py` 절 참고). family 이름 중복 금지,
split은 train/val/test 중 하나만, 최소 1개 이상의 query variant 필요, 정규화된(공백 정리+
casefold) 쿼리 텍스트 중복 금지를 강제한다.
"""

from __future__ import annotations

import pandas as pd

GUIDELINE = """# StoreSearch-KO v1 Annotation Guideline

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
"""


def build_queries_frame(query_cfg: dict) -> pd.DataFrame:
    """query_families_v1.yaml의 families를 queries.csv 스키마의 DataFrame으로 변환한다.

    family 이름 중복, 잘못된 split, variant 0개, 정규화된 쿼리 텍스트 중복을 검사한다.
    """

    rows = []
    seen_queries: dict[str, str] = {}
    seen_families: set[str] = set()

    for family in query_cfg["families"]:
        name = family["family"]
        split = family["split"]
        if name in seen_families:
            raise ValueError(f"Duplicate family: {name}")
        seen_families.add(name)
        if split not in {"train", "val", "test"}:
            raise ValueError(f"Invalid split for {name}: {split}")
        if len(family["queries"]) < 1:
            raise ValueError(f"Family must have >=1 query variant: {name}")

        for i, item in enumerate(family["queries"], start=1):
            query = str(item["text"]).strip()
            normalized = " ".join(query.split()).casefold()
            if normalized in seen_queries:
                raise ValueError(
                    f"Duplicate query text: {query!r}; already used by {seen_queries[normalized]}"
                )
            seen_queries[normalized] = name
            rows.append(
                {
                    "query_id": f"q_{name}_{i:02d}",
                    "query": query,
                    "split": split,
                    "query_family": name,
                    "query_type": str(item["type"]).strip(),
                    "intent_definition": family["intent_definition"],
                    "pool_positive_terms": "|".join(family.get("positive_terms", [])),
                    "pool_boundary_terms": "|".join(family.get("boundary_terms", [])),
                    "query_set_version": query_cfg["query_set_version"],
                    "status": "active",
                }
            )

    return pd.DataFrame(rows)


def build_query_manifest(
    config: dict,
    query_cfg: dict,
    queries: pd.DataFrame,
    queries_sha256: str,
    families_config_sha256: str,
) -> dict:
    return {
        "benchmark_version": config["benchmark_version"],
        "query_set_version": query_cfg["query_set_version"],
        "total_queries": len(queries),
        "families": int(queries["query_family"].nunique()),
        "queries_by_split": queries["split"].value_counts().to_dict(),
        "families_by_split": (
            queries[["query_family", "split"]].drop_duplicates()["split"].value_counts().to_dict()
        ),
        "queries_sha256": queries_sha256,
        "families_config_sha256": families_config_sha256,
    }
