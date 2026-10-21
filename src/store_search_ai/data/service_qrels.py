"""서비스셋 판정 합치기 → qrels (docs/SERVICE_ANNOTATION_GUIDELINE.md 4절).

판정은 (쿼리, 가맹점) 단위이고 위치와 무관하다. 그래서 같은 쿼리를 다른 가정위치(맥락)로 평가해도 판정을 다시 쓴다.

확정 규칙
- 한 명만 판정: 그 점수
- 둘 다 판정, 같은 점수: 그 점수
- 둘 다 판정, 이진 판정(2점 이상 여부)은 같고 점수만 다름(0↔1, 2↔3): **낮은 점수**(보수적)
- 둘 다 판정, 이진 판정이 다름 → 조정 대상
- 한 명이 빈칸(판단 보류)이고 다른 한 명이 점수를 줌: 그 점수
- 아무도 점수를 주지 않음(혼자 판정하고 빈칸) → 조정 대상
조정 결과(`final_relevance`, 빈칸이면 gold 제외)는 다른 모든 규칙보다 우선한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BINARY_THRESHOLD = 2
ADJUDICATION_COLUMNS = ["judgment_id", "query_id", "query", "bundle", "intent_hint", "doc_id", "store_name", "item_text",
                        "market_name", "relevance_A", "relevance_B", "note_A", "note_B", "reason", "final_relevance",
                        "adjudication_note"]


def merge_judgments(sheets: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """판정자별 완료 시트 → judgment_id 한 줄에 판정자별 점수와 확정 상태."""

    names = sorted(sheets)
    base_cols = ["judgment_id", "query_id", "query", "bundle", "intent_hint", "doc_id", "store_name", "item_text", "market_name"]
    frames = []
    for name in names:
        s = sheets[name]
        frames.append(s[base_cols].assign(**{f"relevance_{name}": s["relevance"], f"note_{name}": s["annotator_note"]}))
    merged = frames[0]
    for f in frames[1:]:
        extra = [c for c in f.columns if c not in base_cols]
        merged = merged.merge(f[base_cols + extra], on=base_cols, how="outer")
    rel = merged[[f"relevance_{n}" for n in names]]
    n_scored = rel.notna().sum(axis=1)
    lo, hi = rel.min(axis=1), rel.max(axis=1)
    binary_split = (lo < BINARY_THRESHOLD) & (hi >= BINARY_THRESHOLD)
    in_sheet = sum(merged["judgment_id"].isin(sheets[n]["judgment_id"]).astype(int) for n in names)
    reason = np.select(
        [n_scored == 0, binary_split],
        ["아무도 점수를 주지 않음(판단 보류)", "이진 판정이 다름"],
        default="",
    )
    merged = merged.assign(
        n_annotators=in_sheet, n_scored=n_scored, provisional=np.where(reason == "", lo, np.nan), reason=reason,
    )
    return merged.sort_values(["query_id", "doc_id"]).reset_index(drop=True)


def adjudication_sheet(merged: pd.DataFrame) -> pd.DataFrame:
    need = merged[merged["reason"] != ""].copy()
    for col in ["relevance_A", "relevance_B", "note_A", "note_B"]:
        if col not in need:
            need[col] = np.nan
    need["final_relevance"], need["adjudication_note"] = "", ""
    return need[ADJUDICATION_COLUMNS].reset_index(drop=True)


def apply_adjudication(merged: pd.DataFrame, adjudicated: pd.DataFrame | None) -> pd.DataFrame:
    """조정 결과를 반영해 최종 점수(`relevance`)를 정한다. 조정 대상인데 결과가 없으면 NaN(아직 미확정)."""

    out = merged.assign(relevance=merged["provisional"], adjudicated=False, exclude_from_gold=False)
    if adjudicated is None or adjudicated.empty:
        return out
    adj = adjudicated.set_index("judgment_id")
    hit = out["judgment_id"].isin(adj.index)
    final = out.loc[hit, "judgment_id"].map(adj["final_relevance"])
    final = pd.to_numeric(final, errors="coerce")
    out.loc[hit, "relevance"] = final
    out.loc[hit, "adjudicated"] = True
    out.loc[hit, "exclude_from_gold"] = final.isna()
    return out


def build_qrels(final: pd.DataFrame) -> pd.DataFrame:
    """확정된 점수만 qrels로(query_id, doc_id, relevance). 위치와 무관하다."""

    ok = final["relevance"].notna()
    return final.loc[ok, ["query_id", "doc_id", "relevance"]].astype({"relevance": int}).reset_index(drop=True)
