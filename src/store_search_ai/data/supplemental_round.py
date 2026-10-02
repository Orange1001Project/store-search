"""보충 pooling 라운드 — 특정 쿼리의 pool을 추가로 넓히고, **새로 들어온 (쿼리, 문서)만** 판정해서
기존 gold에 덧붙이는 로직. scripts/16_supplemental_round.py의 CLI 배관을 제외한 핵심 로직.

왜 필요한가: 07번 pooling(lexical 3종 + targeted + random)이 어떤 쿼리의 실제 정답 문서를 하나도 못 찾으면
(예: q_수선_01 "바지 기장 줄이는 곳" — family에 positive_terms가 없고 "바지 기장"이 "수선" 매장과 어휘적으로
안 겹침), 그 쿼리는 관련 문서가 0개라 평가가 성립하지 않는다(12번 final 검증 오류). TREC 관례대로 pool을
추가로 넓히고 새 후보만 판정한다.

원칙:
- 기존 라운드의 판정(A/B, adjudication 결과)은 절대 바꾸지 않는다 — 새 judgment_id만 추가한다.
- 새 후보도 기존과 같은 절차: val/test는 A·B 독립 판정 → 일치하면 자동 확정 → 불일치는 adjudication.
  (09/10번과 같은 함수 `pairwise_report`, `build_adjudication_frame`, `apply_adjudication_patch`를 쓴다.)
- 어떤 용어로 넓혔는지는 라운드 manifest에 남긴다(queries.csv/query_families는 건드리지 않음 — 이미 확정된
  다른 쿼리의 pool이 바뀌지 않게).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from store_search_ai.data.annotation_sheets import (
    add_empty_annotation_fields,
    add_judgment_ids,
    attach_query_metadata,
)


def supplemental_round_names(annotations_root: Path) -> set[str]:
    """`annotations/*/supplemental_manifest.json`이 있는 보충 라운드 이름 전체."""

    return {
        json.loads(path.read_text(encoding="utf-8"))["round"]
        for path in Path(annotations_root).glob("*/supplemental_manifest.json")
    }


def exclude_supplemental_rows(pool: pd.DataFrame, annotations_root: Path) -> pd.DataFrame:
    """본 라운드(08번) 시트를 만들 때 보충 라운드에서 들어온 후보를 뺀다 — 보충 후보는 16번이 따로 판정한다.

    이게 없으면 보충 라운드 뒤에 08번을 다시 돌렸을 때 본 라운드 시트에 보충 후보가 섞인다.
    """

    rounds = supplemental_round_names(annotations_root)
    return pool[~pool["first_seen_round"].isin(rounds)] if rounds else pool


def target_queries_with_terms(queries: pd.DataFrame, query_ids: list[str], terms: list[str]) -> pd.DataFrame:
    """보충할 쿼리만 골라 targeted 채널용 positive 용어를 이번 라운드 용어로 바꾼 사본.

    boundary 용어는 비운다 — 기존 라운드에서 이미 그 용어로 후보를 넣었으므로 다시 돌려도 새 후보가 안 생기고,
    이번 라운드의 목적(빠진 정답 후보 찾기)과도 무관하다.
    """

    missing = sorted(set(query_ids) - set(queries["query_id"]))
    if missing:
        raise ValueError(f"active queries에 없는 query_id: {missing}")
    if not terms:
        raise ValueError("보충 용어(--terms)가 비어 있습니다.")

    target = queries[queries["query_id"].isin(query_ids)].copy()
    target["pool_positive_terms"] = "|".join(terms)
    target["pool_boundary_terms"] = ""
    return target


def select_new_pairs(pool: pd.DataFrame, round_name: str, query_ids: list[str], judged_ids: set[str]) -> pd.DataFrame:
    """이번 라운드에 처음 들어온 (쿼리, 문서) 중 아직 판정된 적 없는 것만 고른다."""

    new = pool[(pool["first_seen_round"] == round_name) & pool["query_id"].isin(query_ids)].copy()
    new = add_judgment_ids(new)
    return new[~new["judgment_id"].isin(judged_ids)]


def build_supplemental_sheet_rows(new_pairs: pd.DataFrame, queries: pd.DataFrame, round_name: str) -> pd.DataFrame:
    """새 후보를 08번 시트와 같은 컬럼 구성(VISIBLE_COLUMNS)으로 만든다(judgment_id·빈 판정칸 포함)."""

    rows = attach_query_metadata(new_pairs, queries)
    return add_empty_annotation_fields(rows, round_name)


def empty_like(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.iloc[0:0].copy()


def merge_into_base_adjudication(base: pd.DataFrame, supplemental: pd.DataFrame) -> pd.DataFrame:
    """기존 라운드의 val/test 최종 판정에 보충 라운드 최종 판정을 덧붙인다.

    덧붙인 행에는 `supplemental_round`(라운드 이름)가 채워진다(원래 행은 비어 있음).
    - 같은 보충 라운드를 다시 merge하면 그 라운드 행만 지우고 새로 붙인다(재실행해도 중복 없음).
    - 보충 행이 원래 판정과 judgment_id가 겹치면 에러 — 기존 판정은 바꾸지 않는다.
    """

    base = base.copy()
    if "supplemental_round" not in base.columns:
        base["supplemental_round"] = pd.NA
    round_names = set(supplemental["supplemental_round"].dropna().unique())
    base = base[~base["supplemental_round"].isin(round_names)]

    overlap = set(base["judgment_id"]) & set(supplemental["judgment_id"])
    if overlap:
        raise ValueError(f"보충 판정이 기존 판정과 겹칩니다(기존 판정은 바꾸지 않음): {sorted(overlap)[:5]}")

    columns = list(base.columns) + [c for c in supplemental.columns if c not in base.columns]
    merged = pd.concat([base, supplemental.reindex(columns=columns)], ignore_index=True)
    return merged[columns]
