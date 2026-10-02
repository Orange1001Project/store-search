"""지금까지 나온 산출물 전체(쿼리/pool/qrels)의 무결성을 점검하는 게이트.

scripts/12_validate_benchmark.py의 CLI 배관(인자 파싱, 파일 저장, 콘솔 출력)을 제외한 핵심
로직 전체 (docs/PIPELINE_CODE_REFERENCE.md `12_validate_benchmark.py` 절 참고). `pilot`은
구조적 검증만, `final`은 config가 정한 최소 기준까지 검사한다.
"""

from __future__ import annotations

import json

import pandas as pd


def validate_query_integrity(queries: pd.DataFrame) -> list[str]:
    errors = []
    if queries["query_id"].duplicated().any():
        errors.append("Duplicate query_id exists")

    norm = queries["query"].astype(str).str.casefold().str.replace(r"\s+", " ", regex=True)
    if norm.duplicated().any():
        errors.append("Duplicate normalized query text exists")

    fam = queries[["query_family", "split"]].drop_duplicates().groupby("query_family")["split"].nunique()
    if (fam > 1).any():
        errors.append(f"Query-family split leakage: {fam[fam > 1].index.tolist()}")

    return errors


def validate_corpus_integrity(corpus: pd.DataFrame) -> list[str]:
    errors = []
    if corpus["doc_id"].duplicated().any():
        errors.append("Corpus doc_id is not unique")
    return errors


def build_base_report(stage: str, queries: pd.DataFrame, corpus: pd.DataFrame) -> dict:
    return {
        "stage": stage,
        "queries": len(queries),
        "query_families": int(queries["query_family"].nunique()),
        "queries_by_split": queries["split"].value_counts().to_dict(),
        "corpus_docs": len(corpus),
    }


def validate_pool(pool: pd.DataFrame, corpus: pd.DataFrame, config: dict) -> tuple[dict, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    sizes = pool.groupby("query_id").size()
    systems: set[str] = set()
    for raw in pool["pool_sources_json"].dropna():
        for source in json.loads(raw):
            if source.startswith("run:"):
                systems.add(source.removeprefix("run:"))

    updates = {
        "pool_rows": len(pool),
        "pool_size_min": int(sizes.min()),
        "pool_size_median": float(sizes.median()),
        "pool_size_mean": float(sizes.mean()),
        "pool_size_max": int(sizes.max()),
        "pool_systems": sorted(systems),
        "pool_system_count": len(systems),
    }

    if int(sizes.min()) < int(config["pooling"]["min_pool_size_warn"]):
        warnings.append(f"Some query pool is smaller than {config['pooling']['min_pool_size_warn']}")

    unknown = set(pool["doc_id"].astype(str)) - set(corpus["doc_id"].astype(str))
    if unknown:
        errors.append(f"Pool contains {len(unknown)} unknown doc_ids")

    return updates, errors, warnings


def validate_qrels(
    qrels: pd.DataFrame, queries: pd.DataFrame, corpus: pd.DataFrame, config: dict
) -> tuple[dict, list[str]]:
    errors: list[str] = []
    allowed = set(map(int, config["relevance"]["grades"]))

    if qrels.duplicated(["query_id", "doc_id"]).any():
        errors.append("Duplicate qrels pair exists")
    if not set(qrels["relevance"].astype(int).unique()).issubset(allowed):
        errors.append("Invalid qrels grade")
    if set(qrels["query_id"].astype(str)) - set(queries["query_id"].astype(str)):
        errors.append("Unknown query_id in qrels")
    if set(qrels["doc_id"].astype(str)) - set(corpus["doc_id"].astype(str)):
        errors.append("Unknown doc_id in qrels")

    threshold = int(config["relevance"]["binary_threshold"])
    rel = qrels.assign(is_rel=qrels["relevance"].astype(int) >= threshold).groupby("query_id")["is_rel"].sum()

    missing_q = set(queries["query_id"].astype(str)) - set(qrels["query_id"].astype(str))
    if missing_q:
        errors.append(f"{len(missing_q)} active queries have no judgments")

    zero = rel[rel < int(config["validation"]["min_relevant_per_query"])]
    if len(zero):
        errors.append(f"{len(zero)} queries have no relevance>={threshold} document")

    counts = qrels.groupby("query_id").size()
    updates = {
        "judgments": len(qrels),
        "judgments_per_query_min": int(counts.min()),
        "judgments_per_query_median": float(counts.median()),
        "binary_relevant_documents": int((qrels["relevance"].astype(int) >= threshold).sum()),
    }
    return updates, errors


_TRUE_VALUES = {"Y", "YES", "TRUE", "1"}


def adjudication_resolution(adjudication: pd.DataFrame) -> dict:
    """val/test 판정 전체(10번 결과 `adjudication_val_test_full_completed.csv`) 중 최종 확정된 비율.

    확정 = A·B 일치로 자동 확정됐거나, adjudication에서 점수를 정했거나, adjudication에서 gold 제외로
    정한 행. 한쪽 애노테이터가 uncertain으로 둔 행도 adjudication에서 결론이 났으면 확정으로 센다
    (팀 원칙: "adjudication에서 확정한 건 확정") — 순수 이중 라벨링 커버리지(`double_annotation_coverage`)는
    그와 별개로 보고만 한다.
    """

    final = pd.to_numeric(adjudication["final_relevance"], errors="coerce")
    excluded = adjudication["exclude_from_gold"].fillna("").astype(str).str.strip().str.upper().isin(_TRUE_VALUES)
    resolved = final.notna() | excluded
    return {
        "adjudication_rows": len(adjudication),
        "adjudication_resolved_rows": int(resolved.sum()),
        "adjudication_excluded_rows": int(excluded.sum()),
        "resolution_coverage": float(resolved.mean()) if len(adjudication) else 1.0,
    }


def validate_final_stage(report: dict, queries: pd.DataFrame, config: dict) -> list[str]:
    errors = []
    if len(queries) < int(config["validation"]["min_total_queries_final"]):
        errors.append("Too few final queries")
    if int((queries["split"] == "test").sum()) < int(config["validation"]["min_test_queries_final"]):
        errors.append("Too few final test queries")
    if report.get("pool_system_count", 0) < int(config["pooling"]["min_pool_systems_final"]):
        errors.append("Pooling systems are not diverse enough for final freeze")

    agreement = report.get("agreement")
    target = float(config["validation"]["target_double_annotation_coverage"])
    if not agreement:
        errors.append("Missing human agreement report")
    elif "resolution_coverage" in agreement:
        # adjudication 결과가 있으면 "최종 확정됐는가"로 판단한다(adjudication_resolution 참고)
        if float(agreement["resolution_coverage"]) < target:
            errors.append("Unresolved val/test judgments after adjudication")
    elif float(agreement.get("double_annotation_coverage", 0)) < target:
        errors.append("Incomplete val/test double annotation")

    return errors


def build_validation_report(
    config: dict,
    stage: str,
    queries: pd.DataFrame,
    corpus: pd.DataFrame,
    pool: pd.DataFrame | None = None,
    qrels: pd.DataFrame | None = None,
    agreement: dict | None = None,
) -> dict:
    """무결성 검증을 전부 수행하고 `validation_{stage}.json` 스키마의 report dict를 만든다.

    pool/qrels/agreement가 아직 없는 파이프라인 단계에서는 None을 넘기면 해당 섹션을
    건너뛴다(`errors`가 비어있으면 `valid: true`).
    """

    errors = [*validate_query_integrity(queries), *validate_corpus_integrity(corpus)]
    warnings: list[str] = []

    report = build_base_report(stage, queries, corpus)

    if pool is not None:
        updates, pool_errors, pool_warnings = validate_pool(pool, corpus, config)
        report.update(updates)
        errors += pool_errors
        warnings += pool_warnings

    if qrels is not None:
        updates, qrels_errors = validate_qrels(qrels, queries, corpus, config)
        report.update(updates)
        errors += qrels_errors

    if agreement is not None:
        report["agreement"] = agreement

    if stage == "final":
        errors += validate_final_stage(report, queries, config)

    report["warnings"] = warnings
    report["errors"] = errors
    report["valid"] = not errors
    return report
