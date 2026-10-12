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


def exclude_supplemental_rows(pool: pd.DataFrame, annotations_root: Path, base_round: str | None = None) -> pd.DataFrame:
    """본 라운드(08번) 시트를 만들 때 보충 라운드에서 들어온 후보를 뺀다 — 보충 후보는 16번이 따로 판정한다.

    이게 없으면 보충 라운드 뒤에 08번을 다시 돌렸을 때 본 라운드 시트에 보충 후보가 섞인다.
    `base_round`를 주면 그 본 라운드에 덧붙는 보충 라운드만 뺀다 — 11/12번은 `base_round`가 같은 보충 판정만 합치므로,
    다른 본 라운드(예: full_annotation_v2)를 새로 시작할 때 보충 후보까지 빼면 그 판정이 어디에도 들어가지 않고 사라진다.
    그런 후보는 새 본 라운드 시트에 포함돼 다시 판정된다.
    """

    rounds = set()
    for manifest_path in Path(annotations_root).glob("*/supplemental_manifest.json"):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if base_round is None or manifest.get("base_round") in (None, base_round):
            rounds.add(manifest["round"])
        else:
            print(f"[안내] 보충 라운드 {manifest['round']}(base_round={manifest.get('base_round')})는 {base_round}에 합쳐지지 "
                  "않으므로 그 후보를 이번 본 라운드 시트에 포함합니다.")
    return pool[~pool["first_seen_round"].isin(rounds)] if rounds else pool


SUPPLEMENTAL_ADJUDICATION_NAME = "adjudication_full_completed.csv"
"""16번 merge가 보충 라운드 폴더(`annotations/{round}/analysis/`)에 남기는 최종 판정 파일."""


def supplemental_adjudication_paths(annotations_root: Path, base_round: str) -> tuple[list[Path], list[str]]:
    """`base_round`에 덧붙일 보충 라운드들의 최종 판정 파일 목록과, 아직 merge 전인 라운드 이름 목록.

    11번(qrels)·12번(검증)이 본 라운드 판정과 이 파일들을 합쳐서 읽는다 — 보충 판정을 본 라운드 파일(10번 출력)에
    직접 쓰지 않으므로, 10번을 다시 돌려도 보충 판정이 사라지지 않는다.
    """

    paths, pending = [], []
    for manifest_path in sorted(Path(annotations_root).glob("*/supplemental_manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("base_round") != base_round:
            continue
        adjudication = manifest_path.parent / "analysis" / SUPPLEMENTAL_ADJUDICATION_NAME
        (paths.append(adjudication) if adjudication.exists() else pending.append(manifest["round"]))
    return paths, pending


def combine_with_supplemental(base: pd.DataFrame, supplements: list[pd.DataFrame]) -> pd.DataFrame:
    """본 라운드 판정 + 보충 라운드 판정(judgment_id가 겹치면 에러 — 기존 판정은 바꾸지 않음)."""

    combined = base
    for supplement in supplements:
        combined = merge_into_base_adjudication(combined, supplement)
    return combined


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


# ============================================================
# 모델 run 기반 보충(dense pooling) — TREC 관례: 성격이 다른 검색기의 상위 k개를 pool에 더한다
# ============================================================

RUN_COLUMNS = ["query_id", "doc_id", "rank", "score", "system"]


def load_supplement_runs(runs_dir: Path, max_depth: int, query_ids: set[str], existing_systems: set[str]) -> pd.DataFrame:
    """`runs_dir/*.csv`(노트북 15번이 만든 모델 run) 중 대상 쿼리의 상위 `max_depth`개만 읽는다.

    파일 하나 = system 하나여야 하고, 이미 pool에 있는 system(lexical 3종 등)과 이름이 겹치면 안 된다 — 같은 이름이면
    pool_sources에서 기존 run의 순위를 덮어써 어느 run이 그 후보를 넣었는지 알 수 없게 된다.
    """

    files = sorted(Path(runs_dir).glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"{runs_dir}에 run CSV가 없습니다 — 노트북 15번 결과(runs/pooling_runs/)를 내려받은 경로를 주세요.")
    frames, names = [], []
    for path in files:
        frame = pd.read_csv(path, encoding="utf-8-sig")
        missing = set(RUN_COLUMNS) - set(frame.columns)
        if missing:
            raise ValueError(f"{path.name}: 필요한 컬럼이 없습니다 {sorted(missing)}")
        systems = set(frame["system"].astype(str))
        if len(systems) != 1:
            raise ValueError(f"{path.name}: 파일 하나에 system이 하나여야 합니다 — {sorted(systems)}")
        names.append(systems.pop())
        frames.append(frame[RUN_COLUMNS])
    if len(set(names)) != len(names):
        raise ValueError(f"같은 system 이름의 run 파일이 두 개 이상입니다: {sorted(names)}")
    runs = pd.concat(frames, ignore_index=True)
    runs["query_id"], runs["doc_id"], runs["system"] = (runs[c].astype(str) for c in ("query_id", "doc_id", "system"))

    clash = set(runs["system"]) & existing_systems
    if clash:
        raise ValueError(f"이미 pool에 있는 system과 이름이 겹칩니다: {sorted(clash)}")
    covered = runs[runs["query_id"].isin(query_ids)]
    seen = covered.groupby("system")["query_id"].agg(set).to_dict()
    short = {s: sorted(query_ids - seen.get(s, set()))[:3] for s in names if query_ids - seen.get(s, set())}
    if short:
        raise ValueError(f"대상 쿼리 일부가 run에 없습니다(앞 3개): {short}")
    return covered[covered["rank"] <= max_depth].reset_index(drop=True)


def new_pair_counts(runs: pd.DataFrame, pooled: set[tuple[str, str]], depths: list[int]) -> pd.DataFrame:
    """depth별로 각 run이 새로 들고 오는 (쿼리, 문서) 수와 전체 합집합 — 판정 비용을 보고 depth를 정하는 표."""

    rows = []
    n_queries = runs["query_id"].nunique()
    for depth in depths:
        top = runs[runs["rank"] <= depth]
        is_new = [(q, d) not in pooled for q, d in zip(top["query_id"], top["doc_id"])]
        new = top[is_new]
        row = {"depth": depth, **new.groupby("system").size().to_dict()}
        union = new.drop_duplicates(["query_id", "doc_id"])
        row["union"] = len(union)
        row["union_per_query"] = round(len(union) / n_queries, 1) if n_queries else 0.0
        rows.append(row)
    return pd.DataFrame(rows).fillna(0)
