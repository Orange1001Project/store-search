"""서비스셋 판정 pool을 만든다 — 쿼리 가정위치 반경 안 가맹점만 후보로(docs/SERVICE_ANNOTATION_GUIDELINE.md 4절).

단계(설정 `judging` 블록, configs/query/service_queryset_v1.yaml)
  1) export  임베딩 run은 Colab에서 만든다(2026-10-20 결정). 반경 안 가맹점·쿼리를 colab_upload/service_eval/로 내보낸다
             → Drive store-search-ai/service_eval/에 올리고 colab/service_dense_runs.ipynb 실행 → 나온 <모델>.csv를
             <benchmark_dir>/runs/에 넣는다.
     (encode  로컬 CPU로 임베딩 캐시를 만드는 대안. 모델당 1시간 안팎)
  2) runs    char BM25 · 키워드 후보 run(로컬)을 반경 안 상위 run_depth개까지 만든다 → <benchmark_dir>/runs/.
             로컬 임베딩 캐시가 있으면 그 run도 만들고, 없으면 Colab에서 받은 run 파일을 그대로 쓴다.
  3) pool    depth별 판정 건수 표(--dry-run) → depth를 정해 판정 시트 생성 → <benchmark_dir>/annotations/<round>/

사용법:
    python scripts/build_service_pool.py export                     # Colab 입력
    python scripts/build_service_pool.py encode                     # (대안) 로컬 임베딩 캐시
    python scripts/build_service_pool.py encode --model configs/models/bge_m3.yaml
    python scripts/build_service_pool.py runs
    python scripts/build_service_pool.py pool --dry-run
    python scripts/build_service_pool.py pool --round service_v1 --depth 10
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.data.service_pool import (
    RUN_COLUMNS,
    annotation_sheet,
    candidates_within,
    double_annotation_queries,
    keyword_run,
    lexical_query,
    pool_pairs,
    runs_outside_radius,
    top_k_run,
)
from store_search_ai.pipeline.common import load_config, sha256_file
from store_search_ai.retrieval.lexical import build_pool_document_texts, fit_bm25_scorer

logger = logging.getLogger(__name__)

CACHE_DIR = Path("data/interim/service_eval")
DOC_TEXT_COLUMN = "search_text_t1_minimal"   # 모델 평가와 같은 문서 텍스트(가맹점명 + 취급품목)


def load_inputs(cfg: dict, bench: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, np.ndarray]]:
    queries = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    queries = queries[queries["status"] == "active"].reset_index(drop=True)
    corpus = pd.read_parquet(bench["corpus_path"], columns=[
        "doc_id", "store_name", "item_text", "market_name", "latitude", "longitude", "geo_status", DOC_TEXT_COLUMN])
    corpus = corpus[corpus["geo_status"] == "VALID"].reset_index(drop=True)
    cands = candidates_within(queries, corpus, cfg["judging"]["judge_radius_km"])
    return queries, corpus, cands


def union_index(cands: dict[str, np.ndarray]) -> np.ndarray:
    return np.unique(np.concatenate(list(cands.values())))


def cache_paths(name: str) -> tuple[Path, Path]:
    return CACHE_DIR / f"emb_{name}.npy", CACHE_DIR / f"emb_{name}.doc_ids.npy"


def encode(args, cfg: dict, bench: dict) -> None:
    from store_search_ai.models.sentence_transformer_encoder import (
        SentenceTransformerEncoder,
    )

    _, corpus, cands = load_inputs(cfg, bench)
    idx = union_index(cands)
    doc_ids = corpus["doc_id"].to_numpy()[idx]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for model_cfg in ([args.model] if args.model else cfg["judging"]["dense_models"]):
        mcfg = load_config(model_cfg)
        emb_path, ids_path = cache_paths(mcfg["name"])
        if emb_path.exists() and ids_path.exists() and np.array_equal(np.load(ids_path, allow_pickle=True), doc_ids):
            logger.info("%s: 캐시가 이미 있음 — 건너뜀", mcfg["name"])
            continue
        logger.info("%s: 반경 안 가맹점 %d개 인코딩", mcfg["name"], len(idx))
        encoder = SentenceTransformerEncoder(mcfg)
        emb = encoder.encode_corpus(corpus[DOC_TEXT_COLUMN].to_numpy()[idx].tolist())
        np.save(emb_path, emb)
        np.save(ids_path, doc_ids.astype(object), allow_pickle=True)
        logger.info("저장: %s", emb_path)


def export(args, cfg: dict, bench: dict) -> None:
    """Colab(colab/service_dense_runs.ipynb) 입력: 판정 반경 안에 드는 가맹점과 활성 쿼리, 반경·depth."""

    jcfg = cfg["judging"]
    queries, corpus, cands = load_inputs(cfg, bench)
    idx = union_index(cands)
    out = Path("colab_upload/service_eval")
    out.mkdir(parents=True, exist_ok=True)
    docs = corpus.iloc[idx][["doc_id", DOC_TEXT_COLUMN, "latitude", "longitude"]].rename(columns={DOC_TEXT_COLUMN: "text"})
    docs.to_csv(out / "docs.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    queries[["query_id", "query", "latitude", "longitude"]].to_csv(out / "queries.csv", index=False, encoding="utf-8-sig",
                                                                  lineterminator="\n")
    meta = {"judge_radius_km": jcfg["judge_radius_km"], "run_depth": jcfg["run_depth"], "docs": len(docs),
            "queries": len(queries), "doc_text": DOC_TEXT_COLUMN, "corpus_path": bench["corpus_path"]}
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("가맹점 %d개, 쿼리 %d개 → %s (Drive store-search-ai/service_eval/에 올림)", len(docs), len(queries), out)


def runs(args, cfg: dict, bench: dict) -> None:
    from store_search_ai.models.sentence_transformer_encoder import (
        SentenceTransformerEncoder,
    )

    jcfg = cfg["judging"]
    queries, corpus, cands = load_inputs(cfg, bench)
    idx = union_index(cands)
    doc_ids = corpus["doc_id"].to_numpy()
    run_dir = Path(jcfg["benchmark_dir"]) / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    depth = jcfg["run_depth"]

    # BM25: 판정 반경 안에 드는 가맹점만으로 색인(IDF도 그 범위 기준)
    texts = build_pool_document_texts(corpus).to_numpy()
    pos = np.full(len(corpus), -1)
    pos[idx] = np.arange(len(idx))
    logger.info("char BM25 색인: %d개", len(idx))
    bm25 = fit_bm25_scorer(pd.Series(texts[idx]))
    frames = [top_k_run(qid, cands[qid], bm25(lexical_query(q, region))[pos[cands[qid]]], doc_ids, depth, "char_bm25")
              for qid, q, region in zip(queries["query_id"], queries["query"], queries["region_text"], strict=True)]
    write_run(pd.concat(frames, ignore_index=True), run_dir / "char_bm25.csv")

    frames = [keyword_run(qid, lexical_query(q, region), cands[qid], texts, doc_ids, jcfg["keyword_per_query"])
              for qid, q, region in zip(queries["query_id"], queries["query"], queries["region_text"], strict=True)]
    write_run(pd.concat(frames, ignore_index=True), run_dir / "keyword.csv")

    for model_cfg in jcfg["dense_models"]:
        mcfg = load_config(model_cfg)
        emb_path, ids_path = cache_paths(mcfg["name"])
        if not emb_path.exists():
            colab_run = run_dir / f"{mcfg['name']}.csv"
            if colab_run.exists():
                logger.info("%s: 로컬 캐시 없음 — Colab에서 받은 run(%s)을 그대로 씀", mcfg["name"], colab_run)
            else:
                logger.warning("%s: run이 없음 — Colab(colab/service_dense_runs.ipynb)에서 만들어 %s에 넣을 것", mcfg["name"], colab_run)
            continue
        cached_ids = np.load(ids_path, allow_pickle=True)
        if not np.array_equal(cached_ids, doc_ids[idx]):
            raise SystemExit(f"{mcfg['name']}: 캐시의 가맹점 목록이 지금 쿼리·반경과 다릅니다 — encode를 다시 실행하세요.")
        emb = np.load(emb_path)
        q_emb = SentenceTransformerEncoder(mcfg).encode_queries(queries["query"].tolist())
        frames = [top_k_run(qid, cands[qid], emb[pos[cands[qid]]] @ q_emb[i], doc_ids, depth, mcfg["name"])
                  for i, qid in enumerate(queries["query_id"])]
        write_run(pd.concat(frames, ignore_index=True), run_dir / f"{mcfg['name']}.csv")


def write_run(run: pd.DataFrame, path: Path) -> None:
    run[RUN_COLUMNS].to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s (%d행, 쿼리 %d개)", path, len(run), run["query_id"].nunique())


def pool(args, cfg: dict, bench: dict) -> None:
    jcfg = cfg["judging"]
    bdir = Path(jcfg["benchmark_dir"])
    run_files = sorted((bdir / "runs").glob("*.csv"))
    if not run_files:
        raise SystemExit("run이 없습니다 — 먼저 runs")
    all_runs = pd.concat([pd.read_csv(p, encoding="utf-8-sig") for p in run_files], ignore_index=True)
    queries, corpus, _cands = load_inputs(cfg, bench)
    stale = {k: v for k, v in runs_outside_radius(all_runs, queries, corpus, jcfg["judge_radius_km"]).items() if v}
    if stale:
        raise SystemExit(f"반경 밖이거나 지금 쿼리에 없는 run 행이 있습니다 {stale} — 쿼리 위치가 바뀐 뒤의 옛 run입니다. "
                         "export → Colab → runs를 다시 하세요.")

    rows = []
    for d in sorted({5, 10, 20, args.depth or jcfg["depth"]}):
        pairs = pool_pairs(all_runs, d)
        per_q = pairs.groupby("query_id").size()
        rows.append({"depth": d, "판정 쌍": len(pairs), "쿼리당 평균": round(per_q.mean(), 1), "쿼리당 최대": int(per_q.max())})
    print(f"========== 판정 건수(시스템 {sorted(all_runs['system'].unique())}, 쿼리 {len(queries)}개) ==========")
    print(pd.DataFrame(rows).to_string(index=False))
    share = jcfg["double_annotation_share"]
    print(f"(쿼리의 {share:.0%}는 A·B 두 명이 판정 — 사람 판정 건수는 그만큼 더 많음)")
    if args.dry_run:
        return
    if not args.round:
        raise SystemExit("--round가 필요합니다.")

    round_dir = bdir / "annotations" / args.round
    if (round_dir / "pool_manifest.json").exists():
        raise SystemExit(f"{round_dir}에 이미 라운드가 있습니다 — 채우는 중인 시트를 덮어쓰지 않도록 다른 --round를 쓰세요.")
    depth = args.depth or jcfg["depth"]
    pairs = pool_pairs(all_runs, depth)
    seed = cfg["random_seed"]
    sheet = annotation_sheet(pairs, queries, corpus, seed)
    double = double_annotation_queries(sorted(pairs["query_id"].unique()), share, seed)
    round_dir.mkdir(parents=True, exist_ok=True)
    sheet.to_csv(round_dir / "annotation_A.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    sheet[sheet["query_id"].isin(double)].to_csv(round_dir / "annotation_B.csv", index=False, encoding="utf-8-sig",
                                                lineterminator="\n")
    pairs.to_csv(round_dir / "pool.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    queries.to_csv(bdir / "queries.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    manifest = {
        "round": args.round,
        "created_at": datetime.now(UTC).isoformat(),
        "judge_radius_km": jcfg["judge_radius_km"],
        "report_radii_km": jcfg["report_radii_km"],
        "depth": depth,
        "queries": int(pairs["query_id"].nunique()),
        "pairs": len(pairs),
        "double_annotation_queries": len(double),
        "double_annotation_pairs": int(sheet["query_id"].isin(double).sum()),
        "runs_sha256": {p.name: sha256_file(p) for p in run_files},
        "queries_sha256": hashlib.sha256((bdir / "queries.csv").read_bytes()).hexdigest(),
        "guideline": "docs/SERVICE_ANNOTATION_GUIDELINE.md + benchmark/storesearch_ko_v1/annotation_guideline.md(v1.2)",
    }
    (round_dir / "pool_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s (A %d행, B %d행)", round_dir, len(sheet), manifest["double_annotation_pairs"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "encode", "runs", "pool"])
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--model", help="encode할 모델 yaml 하나(기본: 설정의 dense_models 전부)")
    parser.add_argument("--round", help="pool: 판정 라운드 이름(예: service_v1)")
    parser.add_argument("--depth", type=int, help="pool: 시스템마다 상위 몇 개(기본: 설정 judging.depth)")
    parser.add_argument("--dry-run", action="store_true", help="pool: 판정 건수 표만")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    {"export": export, "encode": encode, "runs": runs, "pool": pool}[args.command](args, cfg, bench)


if __name__ == "__main__":
    main()
