"""data/query/queryset_final.xlsx -> configs/benchmark/query_families_v1.yaml 변환 로직.

scripts/import_queryset_xlsx.py의 CLI 배관(인자 파싱, 파일 IO, yaml 저장)을 제외한
핵심 변환 로직 전체. 재배정 규칙(RECLASSIFY_QUERIES)과 애매한 slug 목록
(AMBIGUOUS_SLUGS)은 더 이상 이 모듈에 하드코딩하지 않고 호출부가
configs/query/*.yaml에서 읽어 인자로 넘긴다(docs/EXTENDING_DATA.md 참고) —
그래야 query_set 버전이 바뀔 때 이 코드를 건드리지 않고 새 yaml만 추가하면 된다.
"""

from __future__ import annotations

import logging
import random
import re
from collections import defaultdict

import pandas as pd

logger = logging.getLogger(__name__)

BATCHIM_JOSA = {True: "을", False: "를"}


def has_batchim(word: str) -> bool:
    ch = word[-1]
    if not ("가" <= ch <= "힣"):
        return False
    return (ord(ch) - ord("가")) % 28 != 0


def build_intent_definition(family: str, category: str) -> str:
    josa = BATCHIM_JOSA[has_batchim(family)]
    return f"{category} 중 '{family}'{josa} 판매·제공하는 매장"


def infer_slug_family_map(queries: pd.DataFrame, ambiguous_slugs: set[str]) -> dict[str, str]:
    """원본유형에서 영문 slug -> 한글 family 대응을 뽑는다. 불명확하면 제외."""

    pairs: dict[str, set[str]] = defaultdict(set)
    for _, row in queries.iterrows():
        match = re.match(r"^([a-z_]+)\s*/", str(row["원본유형"]))
        if not match:
            continue
        pairs[match.group(1)].add(row["패밀리"])

    clean = {}
    for slug, families in pairs.items():
        if slug in ambiguous_slugs:
            continue
        if len(families) == 1:
            clean[slug] = next(iter(families))
    return clean


def assign_fresh_splits(
    families_by_category: dict[str, list[str]],
    train_ratio: float,
    val_ratio: float,
    rng: random.Random,
) -> dict[str, str]:
    """대분류별로 섞은 뒤 비율대로 train/val/test를 배정한다(카테고리 쏠림 방지)."""

    assignment: dict[str, str] = {}
    for families in families_by_category.values():
        families = sorted(families)
        rng.shuffle(families)
        n = len(families)
        n_train = round(n * train_ratio)
        n_val = round(n * val_ratio)
        for i, fam in enumerate(families):
            if i < n_train:
                assignment[fam] = "train"
            elif i < n_train + n_val:
                assignment[fam] = "val"
            else:
                assignment[fam] = "test"
    return assignment


def apply_reclassification(
    queries: pd.DataFrame,
    reclassify_queries: dict[str, tuple[str, str]],
) -> pd.DataFrame:
    """RECLASSIFY_QUERIES(현재는 configs/query/*.yaml에서 로드)에 정의된 행의 family를 정정한다.

    정정 후에도 "(미판정)" family가 남아 있으면 ValueError를 낸다 — 재배정 규칙이
    누락됐다는 뜻이므로 조용히 넘어가지 않는다.
    """

    queries = queries.copy()
    reclass_mask = queries["질의"].isin(reclassify_queries)
    for query_text, (new_family, reason) in reclassify_queries.items():
        row_mask = queries["질의"] == query_text
        if row_mask.any():
            old_family = queries.loc[row_mask, "패밀리"].iloc[0]
            logger.info("[재배정] '%s': %s -> %s (%s)", query_text, old_family, new_family, reason)
        else:
            logger.warning("[경고] RECLASSIFY_QUERIES에 있는 '%s'를 xlsx에서 찾지 못함", query_text)
    queries.loc[reclass_mask, "패밀리"] = (
        queries.loc[reclass_mask, "질의"].map(lambda q: reclassify_queries[q][0])
    )

    stray_unassigned = queries[queries["패밀리"] == "(미판정)"]
    if len(stray_unassigned):
        raise ValueError(
            f"RECLASSIFY_QUERIES에 없는 '(미판정)' 행이 남아있습니다: "
            f"{stray_unassigned['질의'].tolist()} — 재배정 규칙을 추가하세요."
        )

    return queries


def resolve_splits(
    queries: pd.DataFrame,
    fam_list: pd.DataFrame,
    existing_split_by_family: dict[str, str],
    ambiguous_slugs: set[str],
    random_seed: int,
    train_ratio: float,
    val_ratio: float,
) -> dict[str, str]:
    """family별 split을 결정한다: 기존 yaml 상속 우선, 없으면 새로 균형 배정.

    상속 우선순위: (1) 기존 yaml에 같은 한글 family 이름이 이미 있으면 그대로
    (재실행해도 기존 배정이 안 흔들림), (2) 없으면 원본유형 영문 slug로 대응 시도
    (완전히 새로 만드는 첫 실행 등, 기존 yaml이 영문 slug 체계일 때 대비).
    """

    included_families = sorted(queries["패밀리"].unique())

    inherited_splits: dict[str, str] = {}
    for fam in included_families:
        if fam in existing_split_by_family:
            inherited_splits[fam] = existing_split_by_family[fam]

    slug_family_map = infer_slug_family_map(queries, ambiguous_slugs)
    for slug, korean_family in slug_family_map.items():
        if korean_family not in inherited_splits and slug in existing_split_by_family:
            inherited_splits[korean_family] = existing_split_by_family[slug]

    category_by_family = fam_list.set_index("패밀리")["대분류"].to_dict()

    needs_fresh = [f for f in included_families if f not in inherited_splits]
    families_by_category: dict[str, list[str]] = defaultdict(list)
    for fam in needs_fresh:
        families_by_category[category_by_family.get(fam, "기타")].append(fam)

    rng = random.Random(random_seed)
    fresh_splits = assign_fresh_splits(
        families_by_category, train_ratio=train_ratio, val_ratio=val_ratio, rng=rng
    )

    logger.info("[split 상속] 기존 yaml에서 물려받은 family %d개", len(inherited_splits))
    logger.info("[split 신규배정] 대분류별 균형+무작위로 새로 배정한 family %d개", len(fresh_splits))

    return {**fresh_splits, **inherited_splits}


def parse_corrections(raw: dict) -> tuple[dict[str, tuple[str, str]], set[str]]:
    """configs/query/*.yaml을 yaml.safe_load한 dict를 (reclassify_queries, ambiguous_slugs)로 변환한다."""

    reclassify_queries = {
        item["query"]: (item["family"], item["reason"])
        for item in raw.get("reclassify_queries", [])
    }
    ambiguous_slugs = set(raw.get("ambiguous_slugs", []))
    return reclassify_queries, ambiguous_slugs


def build_query_families(
    queries: pd.DataFrame,
    fam_list: pd.DataFrame,
    existing_split_by_family: dict[str, str],
    reclassify_queries: dict[str, tuple[str, str]],
    ambiguous_slugs: set[str],
    random_seed: int,
    query_set_version: str,
    train_ratio: float = 0.42,
    val_ratio: float = 0.22,
) -> dict:
    """xlsx의 통합질의/패밀리목록 시트를 query_families_v1.yaml 스키마의 dict로 변환한다.

    scripts/import_queryset_xlsx.py가 xlsx를 읽어 이 함수를 호출하고, 반환값을
    그대로 yaml.safe_dump한다. 부작용(파일 IO) 없이 순수 변환만 한다 — 테스트와
    golden-file 회귀 검증이 파일 없이 이 함수만으로 가능하게 하기 위함.
    """

    total_rows = len(queries)
    queries = apply_reclassification(queries, reclassify_queries)
    logger.info("[포함] 전체 질의 %d개 전부 유지 (family당 최소 variant 제한 없음)", total_rows)

    included_families = sorted(queries["패밀리"].unique())
    category_by_family = fam_list.set_index("패밀리")["대분류"].to_dict()

    final_split = resolve_splits(
        queries=queries,
        fam_list=fam_list,
        existing_split_by_family=existing_split_by_family,
        ambiguous_slugs=ambiguous_slugs,
        random_seed=random_seed,
        train_ratio=train_ratio,
        val_ratio=val_ratio,
    )
    split_counts = pd.Series(final_split).value_counts()
    logger.info("[split 분포] %s", split_counts.to_dict())

    out_families = []
    for fam in included_families:
        sub = queries[queries["패밀리"] == fam]
        category = category_by_family.get(fam, "기타")

        positive_terms = sorted(
            set(sub.loc[sub["유형"].isin(["T1 정확표기", "T2 동의어"]), "질의"].tolist())
        )
        boundary_terms = []
        for value in sub["함정"].dropna():
            boundary_terms.extend(part.strip() for part in str(value).split(",") if part.strip())
        boundary_terms = sorted(set(boundary_terms))

        query_items = [
            {"type": str(row["유형"]).strip(), "text": str(row["질의"]).strip()}
            for _, row in sub.iterrows()
        ]

        out_families.append(
            {
                "family": fam,
                "split": final_split[fam],
                "intent_definition": build_intent_definition(fam, category),
                "positive_terms": positive_terms,
                "boundary_terms": boundary_terms,
                "queries": query_items,
            }
        )

    total_queries = sum(len(f["queries"]) for f in out_families)
    logger.info("[요약] family %d개, 질의 %d개", len(out_families), total_queries)

    return {
        "query_set_version": query_set_version,
        "families": out_families,
    }
