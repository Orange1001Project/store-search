"""lexical run + 규칙 기반 targeted 채널 + 결정적 random negative를 합쳐서 사람이 실제로
라벨링할 후보 pool(candidate_pool_internal.csv)을 만드는 로직 — "pooling"의 핵심 단계.

scripts/07_build_annotation_pool.py의 CLI 배관(인자 파싱, 콘솔 출력)을 제외한 핵심 로직
전체 (docs/PIPELINE_CODE_REFERENCE.md `07_build_annotation_pool.py` 절 참고). 세 채널:

1. `run:{system}` — 06의 lexical run 각각의 상위 N개
2. `target:positive:{term}`/`target:boundary:{term}` — 취급품목/가맹점명에 직접 문자열
   매칭시켜 찾아낸 경계 사례 후보. **relevance 점수에는 전혀 반영되지 않고, 오직
   "사람이 볼 후보에 포함되느냐"만 결정한다.**
3. `random` — `base_seed + crc32(query_id)`로 시드를 고정한 결정적 랜덤 샘플

같은 (query_id, doc_id)가 여러 채널에서 나오면 pool_sources에 채널별 근거가 모두
누적된다. `--round`로 여러 번 누적 호출 가능 — 이전 candidate_pool_internal.csv가 있으면
그 위에 누적한다(라운드를 여러 번 돌려도 이전 후보가 사라지지 않음).
"""

from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

SEP_RE = re.compile(r"\s*,\s*")

CandidateKey = tuple[str, str]
Candidates = dict[CandidateKey, dict]


def normalize(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return "".join(str(value).casefold().split())


def split_terms(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [x.strip() for x in str(value).split("|") if x.strip()]


def item_parts(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [x.strip() for x in SEP_RE.split(str(value)) if x.strip()]


def source_dict(value: object) -> dict[str, dict]:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {}
    return json.loads(str(value))


def precompute_match_index(corpus: pd.DataFrame) -> tuple[list[list[str]], list[str]]:
    """corpus 1회 순회로 정규화된 item parts / store_name을 미리 만들어 둔다.

    원래 구현은 term(positive/boundary term)마다 매번 corpus 전체를 다시 파싱했다 —
    query family 수 x term 수가 늘어나면(주유소/학원 등 추가) 그만큼 반복 비용이
    곱해진다. item_text 파싱은 term과 무관하므로 한 번만 하면 된다.
    """

    item_parts_list = [[normalize(part) for part in item_parts(value)] for value in corpus["item_text"]]
    store_name_norm = [normalize(value) for value in corpus["store_name"]]
    return item_parts_list, store_name_norm


def targeted_match_mask(
    item_parts_list: list[list[str]], store_name_norm: list[str], term: str
) -> np.ndarray:
    """Coverage-only channel. Prefer item components; use store name only if item is missing."""

    t = normalize(term)
    result = np.zeros(len(item_parts_list), dtype=bool)
    for i, parts in enumerate(item_parts_list):
        matched = False
        for p in parts:
            if p and t and (p == t or t in p or (len(p) >= 2 and p in t)):
                matched = True
                break
        if not parts:
            s = store_name_norm[i]
            if len(t) >= 2 and t in s:
                matched = True
        result[i] = matched
    return result


# ============================================================
# Loading
# ============================================================

def load_pooling_runs(runs_dir: Path, run_depth: int) -> pd.DataFrame:
    run_files = sorted(runs_dir.glob("*.csv"))
    if not run_files:
        raise FileNotFoundError(f"No pooling run CSV files in {runs_dir}")

    runs = []
    for path in run_files:
        frame = pd.read_csv(path)
        required = {"query_id", "doc_id", "rank", "score", "system"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{path} missing columns: {sorted(missing)}")
        runs.append(frame[frame["rank"] <= run_depth].copy())

    return pd.concat(runs, ignore_index=True)


def load_existing_candidates(pool_path: Path) -> Candidates:
    """이전 라운드에서 만든 candidate_pool_internal.csv가 있으면 이어받는다."""

    candidates: Candidates = {}
    if not pool_path.exists():
        return candidates

    old = pd.read_csv(pool_path)
    for r in old.itertuples(index=False):
        candidates[(str(r.query_id), str(r.doc_id))] = {
            "query_id": str(r.query_id),
            "doc_id": str(r.doc_id),
            "pool_sources": source_dict(r.pool_sources_json),
            "first_seen_round": str(r.first_seen_round),
        }
    return candidates


# ============================================================
# Accumulation
# ============================================================

def add_candidate(
    candidates: Candidates, qid: str, doc_id: str, source: str, metadata: dict, round_name: str
) -> None:
    key = (qid, doc_id)
    if key not in candidates:
        candidates[key] = {
            "query_id": qid, "doc_id": doc_id, "pool_sources": {}, "first_seen_round": round_name,
        }
    candidates[key]["pool_sources"][source] = metadata


def accumulate_run_candidates(candidates: Candidates, run_df: pd.DataFrame, round_name: str) -> None:
    """Each retrieval system contributes independently."""

    for r in run_df.itertuples(index=False):
        add_candidate(
            candidates, str(r.query_id), str(r.doc_id), f"run:{r.system}",
            {"rank": int(r.rank), "score": float(r.score)}, round_name,
        )


def accumulate_targeted_candidates(
    candidates: Candidates,
    queries: pd.DataFrame,
    corpus: pd.DataFrame,
    item_parts_list: list[list[str]],
    store_name_norm: list[str],
    targeted_per_term: int,
    round_name: str,
) -> None:
    """Hidden targeted coverage channels; never part of a model score."""

    for q in queries.itertuples(index=False):
        for kind, raw_terms in [("positive", q.pool_positive_terms), ("boundary", q.pool_boundary_terms)]:
            for term in split_terms(raw_terms):
                idxs = np.flatnonzero(targeted_match_mask(item_parts_list, store_name_norm, term))
                idxs = sorted(idxs, key=lambda i: str(corpus.iloc[i]["doc_id"]))[:targeted_per_term]
                for idx in idxs:
                    add_candidate(
                        candidates, str(q.query_id), str(corpus.iloc[idx]["doc_id"]),
                        f"target:{kind}:{term}", {"matched_term": term}, round_name,
                    )


def accumulate_random_candidates(
    candidates: Candidates,
    queries: pd.DataFrame,
    corpus: pd.DataFrame,
    base_seed: int,
    random_per_query: int,
    round_name: str,
) -> None:
    """Deterministic random negatives, independent of retrieval scores."""

    all_doc_ids = corpus["doc_id"].astype(str).tolist()
    for q in queries.itertuples(index=False):
        qid = str(q.query_id)
        already = {d for (qq, d) in candidates if qq == qid}
        available = [d for d in all_doc_ids if d not in already]
        if not available:
            continue
        seed = base_seed + zlib.crc32(qid.encode("utf-8"))
        rng = np.random.default_rng(seed)
        sample = rng.choice(
            np.array(available, dtype=object), size=min(random_per_query, len(available)), replace=False
        )
        for doc_id in sample.tolist():
            add_candidate(candidates, qid, str(doc_id), "random", {"seed": int(seed)}, round_name)


# ============================================================
# Assembly
# ============================================================

def build_pool_frame(
    candidates: Candidates, queries: pd.DataFrame, corpus: pd.DataFrame, round_name: str
) -> pd.DataFrame:
    corpus_index = {str(doc): i for i, doc in enumerate(corpus["doc_id"])}
    query_lookup = queries.set_index("query_id").to_dict("index")

    rows = []
    for (qid, doc_id), value in candidates.items():
        if qid not in query_lookup:
            continue
        if doc_id not in corpus_index:
            raise ValueError(f"Pool doc_id not in corpus: {doc_id}")

        doc = corpus.iloc[corpus_index[doc_id]]
        q = query_lookup[qid]
        sources = value["pool_sources"]
        run_ranks = [int(v["rank"]) for k, v in sources.items() if k.startswith("run:") and "rank" in v]

        rows.append(
            {
                "query_id": qid, "query": q["query"], "split": q["split"],
                "query_family": q["query_family"], "doc_id": doc_id,
                "store_name": doc.get("store_name"), "item_text": doc.get("item_text"),
                "market_name": doc.get("market_name"), "market_type": doc.get("market_type"),
                "source_region": doc.get("source_region"),
                "pool_sources_json": json.dumps(sources, ensure_ascii=False, sort_keys=True),
                "pool_source_count": len(sources),
                "best_run_rank": min(run_ranks) if run_ranks else pd.NA,
                "first_seen_round": value["first_seen_round"],
                "last_updated_round": round_name,
            }
        )

    return pd.DataFrame(rows).sort_values(["query_id", "best_run_rank", "doc_id"], na_position="last")


def build_pool_stats(pool: pd.DataFrame, run_df: pd.DataFrame, round_name: str) -> dict:
    per_query = pool.groupby("query_id").size()
    systems = sorted(run_df["system"].astype(str).unique().tolist())

    return {
        "round": round_name,
        "pool_rows": len(pool),
        "queries": int(pool["query_id"].nunique()),
        "pool_systems": systems,
        "pool_system_count": len(systems),
        "mean_pool_size": float(per_query.mean()),
        "min_pool_size": int(per_query.min()),
        "median_pool_size": float(per_query.median()),
        "max_pool_size": int(per_query.max()),
        "first_seen_in_this_round": int((pool["first_seen_round"] == round_name).sum()),
    }


def merge_pool_history(
    existing_history: pd.DataFrame | None, stats: dict, round_name: str
) -> pd.DataFrame:
    """같은 라운드로 재실행하면 그 라운드 행만 교체하고, 나머지 라운드 기록은 보존한다."""

    row = pd.DataFrame([stats])
    if existing_history is None:
        return row
    history = existing_history[existing_history["round"] != round_name]
    return pd.concat([history, row], ignore_index=True)
