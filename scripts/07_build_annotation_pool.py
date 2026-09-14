from __future__ import annotations

import argparse
import json
import re
import zlib
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.pipeline.common import load_active_queries, load_config

SEP_RE = re.compile(r"\s*,\s*")


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


def precompute_match_index(
    corpus: pd.DataFrame,
) -> tuple[list[list[str]], list[str]]:
    """corpus 1회 순회로 정규화된 item parts / store_name을 미리 만들어 둔다.

    원래 구현은 term(positive/boundary term) 마다 매번 corpus 전체를 다시
    파싱했다 — query family 수 x term 수가 늘어나면(주유소/학원 등 추가) 그만큼
    반복 비용이 곱해진다. item_text 파싱은 term과 무관하므로 한 번만 하면 된다.
    """

    item_parts_list = [
        [normalize(part) for part in item_parts(value)]
        for value in corpus["item_text"]
    ]

    store_name_norm = [
        normalize(value) for value in corpus["store_name"]
    ]

    return item_parts_list, store_name_norm


def targeted_match_mask(
    item_parts_list: list[list[str]],
    store_name_norm: list[str],
    term: str,
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


def source_dict(value: object) -> dict[str, dict]:
    if value is None or pd.isna(value) or str(value).strip() == "":
        return {}
    return json.loads(str(value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--round", required=True, help="e.g. lexical_v1 or dense_round1")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    runs_dir = benchmark_dir / "runs" / "pooling"
    corpus = pd.read_parquet(config["corpus_path"])
    queries = load_active_queries(benchmark_dir)

    run_depth = int(config["pooling"]["run_depth"])
    targeted_per_term = int(config["pooling"]["targeted_per_term"])
    random_per_query = int(config["pooling"]["random_per_query"])
    base_seed = int(config["pooling"]["random_seed"])

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
    run_df = pd.concat(runs, ignore_index=True)

    corpus_index = {str(doc): i for i, doc in enumerate(corpus["doc_id"])}
    candidates: dict[tuple[str, str], dict] = {}
    pool_path = benchmark_dir / "candidate_pool_internal.csv"

    if pool_path.exists():
        old = pd.read_csv(pool_path)
        for r in old.itertuples(index=False):
            candidates[(str(r.query_id), str(r.doc_id))] = {
                "query_id": str(r.query_id),
                "doc_id": str(r.doc_id),
                "pool_sources": source_dict(r.pool_sources_json),
                "first_seen_round": str(r.first_seen_round),
            }

    def add(qid: str, doc_id: str, source: str, metadata: dict) -> None:
        key = (qid, doc_id)
        if key not in candidates:
            candidates[key] = {
                "query_id": qid, "doc_id": doc_id,
                "pool_sources": {}, "first_seen_round": args.round,
            }
        candidates[key]["pool_sources"][source] = metadata

    # Each retrieval system contributes independently.
    for r in run_df.itertuples(index=False):
        add(str(r.query_id), str(r.doc_id), f"run:{r.system}",
            {"rank": int(r.rank), "score": float(r.score)})

    # Hidden targeted coverage channels; never part of a model score.
    item_parts_list, store_name_norm = precompute_match_index(corpus)
    for q in queries.itertuples(index=False):
        for kind, raw_terms in [("positive", q.pool_positive_terms), ("boundary", q.pool_boundary_terms)]:
            for term in split_terms(raw_terms):
                idxs = np.flatnonzero(
                    targeted_match_mask(item_parts_list, store_name_norm, term)
                )
                idxs = sorted(idxs, key=lambda i: str(corpus.iloc[i]["doc_id"]))[:targeted_per_term]
                for idx in idxs:
                    add(str(q.query_id), str(corpus.iloc[idx]["doc_id"]),
                        f"target:{kind}:{term}", {"matched_term": term})

    # Deterministic random negatives, independent of retrieval scores.
    all_doc_ids = corpus["doc_id"].astype(str).tolist()
    for q in queries.itertuples(index=False):
        qid = str(q.query_id)
        already = {d for (qq, d) in candidates if qq == qid}
        available = [d for d in all_doc_ids if d not in already]
        if available:
            seed = base_seed + zlib.crc32(qid.encode("utf-8"))
            rng = np.random.default_rng(seed)
            sample = rng.choice(np.array(available, dtype=object),
                                size=min(random_per_query, len(available)), replace=False)
            for doc_id in sample.tolist():
                add(qid, str(doc_id), "random", {"seed": int(seed)})

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
        run_ranks = [int(v["rank"]) for k, v in sources.items()
                     if k.startswith("run:") and "rank" in v]
        rows.append({
            "query_id": qid, "query": q["query"], "split": q["split"],
            "query_family": q["query_family"], "doc_id": doc_id,
            "store_name": doc.get("store_name"), "item_text": doc.get("item_text"),
            "market_name": doc.get("market_name"), "market_type": doc.get("market_type"),
            "source_region": doc.get("source_region"),
            "pool_sources_json": json.dumps(sources, ensure_ascii=False, sort_keys=True),
            "pool_source_count": len(sources),
            "best_run_rank": min(run_ranks) if run_ranks else pd.NA,
            "first_seen_round": value["first_seen_round"],
            "last_updated_round": args.round,
        })

    pool = pd.DataFrame(rows).sort_values(["query_id", "best_run_rank", "doc_id"], na_position="last")
    pool.to_csv(pool_path, index=False, encoding="utf-8-sig")
    per_query = pool.groupby("query_id").size()
    systems = sorted(run_df["system"].astype(str).unique().tolist())
    stats = {
        "round": args.round, "pool_rows": int(len(pool)),
        "queries": int(pool["query_id"].nunique()),
        "pool_systems": systems, "pool_system_count": len(systems),
        "mean_pool_size": float(per_query.mean()), "min_pool_size": int(per_query.min()),
        "median_pool_size": float(per_query.median()), "max_pool_size": int(per_query.max()),
        "first_seen_in_this_round": int((pool["first_seen_round"] == args.round).sum()),
    }
    (benchmark_dir / "pool_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    history_path = benchmark_dir / "pool_history.csv"
    row = pd.DataFrame([stats])
    if history_path.exists():
        history = pd.read_csv(history_path)
        history = history[history["round"] != args.round]
        row = pd.concat([history, row], ignore_index=True)
    row.to_csv(history_path, index=False, encoding="utf-8-sig")

    print("========== INTERNAL POOL BUILT ==========")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print("NOTE: candidate_pool_internal.csv contains provenance and must not be annotated directly.")


if __name__ == "__main__":
    main()
