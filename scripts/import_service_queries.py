"""사람이 쓴 서비스셋 쿼리를 하나의 쿼리 표(CSV)로 가져온다. 설명은 docs/SERVICE_QUERYSET.md 4절.

입력(설정 `import` 블록)
  - 작성자 완료본(data/query/writers_completed/…_completed.xlsx): W1~W3의 A·C·D·E
  - 팀 작성본(data/query/service_queryset_v1_team_completed.xlsx): 사람이 쓴 B 150개만 쓴다(나머지는 AI 초안이라 버림)
  - 설정 `import.extra_queries`: 진행자가 직접 더한 쿼리
  - 서비스셋 템플릿(B_가맹점표본·D_시장표본 좌표), 기존 벤치마크 쿼리(중복 확인)

출력
  - data/query/service_queries_v1.csv           평가 쿼리(query_id, split dev/test, status, 가정위치 …)
  - data/query/service_queries_v1.meta.json     원본 sha256, 묶음·split별 개수, seed

다시 실행해도 같은 결과가 나온다(split은 설정 seed, 자동 가정위치는 쿼리 문자열 해시).

사용법:
    python scripts/import_service_queries.py
    python scripts/import_service_queries.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from store_search_ai.data.service_import import (
    build_service_queries,
    changes_from_previous,
    old_benchmark_splits,
    split_fixed_from,
    team_b_rows,
    writer_rows,
)
from store_search_ai.pipeline.common import load_config, sha256_file

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--families", default="configs/benchmark/query_families_v1.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    icfg = cfg["import"]
    bench = load_config(args.benchmark_config)

    sources = icfg["writers_completed"] if isinstance(icfg["writers_completed"], list) else [icfg["writers_completed"]]
    writers = pd.concat([writer_rows(pd.read_excel(src, sheet_name=None)) for src in sources if Path(src).exists()],
                        ignore_index=True)
    team = pd.read_excel(icfg["team_completed"], sheet_name="쿼리입력")
    b_rows, _ = team_b_rows(team, icfg["team_human_methods"])   # 팀 작성본의 나머지는 AI 초안이라 쓰지 않는다
    extra = pd.DataFrame([
        {"query": e["query"], "bundle": e["bundle"], "intent": e.get("intent", ""), "region_text": "", "location_id": "",
         "basis_id": "", "writer": "facilitator", "note": "진행자 추가"}
        for e in icfg.get("extra_queries", [])
    ])
    rows = pd.concat([b_rows, writers, extra], ignore_index=True)
    drop = {(d["writer"], d["basis_id"]): d["reason"] for d in icfg.get("drop_rows", [])}
    if drop:   # 작성자 한 줄만 뺀다(같은 문자열의 다른 묶음 쿼리는 그대로 — exclude_queries는 문자열 단위라 둘 다 빠짐)
        keys = list(zip(rows["writer"], rows["basis_id"], strict=True))
        unmatched = set(drop) - set(keys)
        if unmatched:
            raise SystemExit(f"설정 import.drop_rows 중 맞는 작성 줄이 없는 항목: {sorted(unmatched)}")
        hit = pd.Series([k in drop for k in keys], index=rows.index)
        for w, b, q in rows.loc[hit, ["writer", "basis_id", "query"]].itertuples(index=False):
            logger.info("작성 줄 뺌: %s %s %s — %s", w, b, q, drop[(w, b)])
        rows = rows[~hit].reset_index(drop=True)

    template = pd.read_excel(cfg["output_path"], sheet_name=["B_가맹점표본", "D_시장표본"])
    families = load_config(args.families)["families"]
    inactive = {r["query_id"] for r in load_config(bench["query_set"]["inactive_queries_path"])["inactive_queries"]}

    corpus = pd.read_parquet(bench["corpus_path"],
                             columns=["doc_id", "store_name", "item_text", "latitude", "longitude", "geo_status"])
    points = corpus.loc[corpus["geo_status"] == "VALID", ["doc_id", "latitude", "longitude"]]
    out = Path(icfg["output"])
    previous = pd.read_csv(out, encoding="utf-8-sig", keep_default_na=False) if out.exists() else None
    queries = build_service_queries(
        rows, icfg["bundle_priority"], old_benchmark_splits(families, inactive), icfg["exclude_queries"],
        template["B_가맹점표본"], template["D_시장표본"], points, cfg["split"]["dev_share"], cfg["random_seed"],
        split_fixed_from(previous) if previous is not None else None, previous,
    )
    # 판정(qrels)·사례·dev/test가 기존 query_id에 묶여 있다 — 기존 쿼리가 없어지거나 문자열·묶음·split·위치가 바뀌면 멈춘다(dry-run도)
    changed = changes_from_previous(previous, queries) if previous is not None else []
    if changed:
        raise SystemExit(f"기존 쿼리 {len(changed)}개가 바뀝니다 — 판정과 어긋나므로 멈춥니다:\n" + "\n".join(changed[:20]))

    # E는 정말 가맹점이 없는지 판정 전에 볼 수 있게, 상호·취급품목에 그 문자열이 몇 번 나오는지 붙인다
    text = (corpus["store_name"].fillna("") + " " + corpus["item_text"].fillna("")).str.replace(" ", "", regex=False)
    queries["corpus_hits"] = [
        str(int(text.str.contains(q.replace(" ", ""), regex=False).sum())) if b == "E" else ""
        for q, b in zip(queries["query"], queries["bundle"], strict=True)
    ]

    keywords = cfg["judging"]["attribute_keywords"]
    queries["attribute"] = queries["query"].map(lambda q: "|".join(k for k in keywords if k in q))

    active = queries[queries["status"] == "active"]
    counts = active.groupby(["bundle", "split"]).size().unstack(fill_value=0)
    logger.info("입력 %d줄(사람 B %d + 작성자 %d + 진행자 %d) → 쿼리 %d개(합친 중복 %d)", len(rows), len(b_rows),
                len(writers), len(extra), len(queries), len(rows) - len(queries))
    logger.info("묶음 × split(활성):\n%s", counts.to_string())
    excluded = queries[queries["status"] == "excluded"]
    if len(excluded):
        logger.info("제외 %d개:\n%s", len(excluded), excluded[["query_id", "query", "exclude_reason"]].to_string(index=False))
    logger.info("여러 명이 쓴 쿼리 %d개, 다른 묶음에도 나온 쿼리 %d개, 기존 벤치마크 val/test와 같은 문자열 %d개",
                (queries["n_writers"] > 1).sum(), (queries["also_in_bundles"] != "").sum(),
                queries["old_benchmark_split"].isin(["val", "test"]).sum())
    logger.info("속성 쿼리 %d개: %s", (queries["attribute"] != "").sum(),
                ", ".join(queries.loc[queries["attribute"] != "", "query"]))
    logger.info("가정위치 출처: %s / B 지역표현 자동 추출 %d개", queries["location_source"].value_counts().to_dict(),
                (queries["region_text_source"] == "auto").sum())
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return

    queries.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    meta = {
        "version": cfg["version"],
        "seed": cfg["random_seed"],
        "dev_share": cfg["split"]["dev_share"],
        "sources": {p: sha256_file(Path(p)) for p in [*sources, icfg["team_completed"], cfg["output_path"]] if Path(p).exists()},
        "queries": len(queries),
        "active_by_bundle_split": {b: counts.loc[b].to_dict() for b in counts.index},
        "excluded": len(excluded),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s", out)


if __name__ == "__main__":
    main()
