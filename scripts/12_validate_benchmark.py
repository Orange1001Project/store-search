from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_active_queries, load_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--stage", choices=["pilot","final"], default="pilot")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    queries = load_active_queries(benchmark_dir)
    corpus = pd.read_parquet(config["corpus_path"])
    errors, warnings = [], []

    if queries["query_id"].duplicated().any(): errors.append("Duplicate query_id exists")
    norm = queries["query"].astype(str).str.casefold().str.replace(r"\s+"," ",regex=True)
    if norm.duplicated().any(): errors.append("Duplicate normalized query text exists")
    fam = queries[["query_family","split"]].drop_duplicates().groupby("query_family")["split"].nunique()
    if (fam > 1).any(): errors.append(f"Query-family split leakage: {fam[fam>1].index.tolist()}")
    if corpus["doc_id"].duplicated().any(): errors.append("Corpus doc_id is not unique")

    report = {
        "stage": args.stage, "queries": int(len(queries)),
        "query_families": int(queries["query_family"].nunique()),
        "queries_by_split": queries["split"].value_counts().to_dict(),
        "corpus_docs": int(len(corpus)),
    }

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    if pool_path.exists():
        pool = pd.read_csv(pool_path)
        sizes = pool.groupby("query_id").size()
        systems = set()
        for raw in pool["pool_sources_json"].dropna():
            for source in json.loads(raw):
                if source.startswith("run:"): systems.add(source.removeprefix("run:"))
        report.update({
            "pool_rows": int(len(pool)), "pool_size_min": int(sizes.min()),
            "pool_size_median": float(sizes.median()), "pool_size_mean": float(sizes.mean()),
            "pool_size_max": int(sizes.max()), "pool_systems": sorted(systems),
            "pool_system_count": len(systems),
        })
        if int(sizes.min()) < int(config["pooling"]["min_pool_size_warn"]):
            warnings.append(f"Some query pool is smaller than {config['pooling']['min_pool_size_warn']}")
        unknown = set(pool["doc_id"].astype(str)) - set(corpus["doc_id"].astype(str))
        if unknown: errors.append(f"Pool contains {len(unknown)} unknown doc_ids")

    qrels_path = benchmark_dir / "qrels.csv"
    if qrels_path.exists():
        qrels = pd.read_csv(qrels_path)
        allowed = set(map(int, config["relevance"]["grades"]))
        if qrels.duplicated(["query_id","doc_id"]).any(): errors.append("Duplicate qrels pair exists")
        if not set(qrels["relevance"].astype(int).unique()).issubset(allowed): errors.append("Invalid qrels grade")
        if set(qrels["query_id"].astype(str)) - set(queries["query_id"].astype(str)): errors.append("Unknown query_id in qrels")
        if set(qrels["doc_id"].astype(str)) - set(corpus["doc_id"].astype(str)): errors.append("Unknown doc_id in qrels")
        threshold = int(config["relevance"]["binary_threshold"])
        rel = qrels.assign(is_rel=qrels["relevance"].astype(int)>=threshold).groupby("query_id")["is_rel"].sum()
        missing_q = set(queries["query_id"].astype(str)) - set(qrels["query_id"].astype(str))
        if missing_q: errors.append(f"{len(missing_q)} active queries have no judgments")
        zero = rel[rel < int(config["validation"]["min_relevant_per_query"])]
        if len(zero): errors.append(f"{len(zero)} queries have no relevance>={threshold} document")
        counts = qrels.groupby("query_id").size()
        report.update({
            "judgments": int(len(qrels)), "judgments_per_query_min": int(counts.min()),
            "judgments_per_query_median": float(counts.median()),
            "binary_relevant_documents": int((qrels["relevance"].astype(int)>=threshold).sum()),
        })

    agreement_path = benchmark_dir / "agreement_report.json"
    if agreement_path.exists(): report["agreement"] = json.loads(agreement_path.read_text(encoding="utf-8"))

    if args.stage == "final":
        if len(queries) < int(config["validation"]["min_total_queries_final"]): errors.append("Too few final queries")
        if int((queries["split"]=="test").sum()) < int(config["validation"]["min_test_queries_final"]): errors.append("Too few final test queries")
        if report.get("pool_system_count",0) < int(config["pooling"]["min_pool_systems_final"]): errors.append("Pooling systems are not diverse enough for final freeze")
        agreement = report.get("agreement")
        if not agreement: errors.append("Missing human agreement report")
        elif float(agreement.get("double_annotation_coverage",0)) < float(config["validation"]["target_double_annotation_coverage"]): errors.append("Incomplete val/test double annotation")

    report["warnings"] = warnings; report["errors"] = errors; report["valid"] = not errors
    (benchmark_dir / f"validation_{args.stage}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("========== BENCHMARK VALIDATION ==========")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if errors: raise SystemExit(1)


if __name__ == "__main__":
    main()
