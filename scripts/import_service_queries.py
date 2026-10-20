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
    old_benchmark_splits,
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

    writers = writer_rows(pd.read_excel(icfg["writers_completed"], sheet_name=None))
    team = pd.read_excel(icfg["team_completed"], sheet_name="쿼리입력")
    b_rows, _ = team_b_rows(team, icfg["team_human_methods"])   # 팀 작성본의 나머지는 AI 초안이라 쓰지 않는다
    extra = pd.DataFrame([
        {"query": e["query"], "bundle": e["bundle"], "intent": e.get("intent", ""), "region_text": "", "location_id": "",
         "basis_id": "", "writer": "facilitator", "note": "진행자 추가"}
        for e in icfg.get("extra_queries", [])
    ])
    rows = pd.concat([b_rows, writers, extra], ignore_index=True)

    template = pd.read_excel(cfg["output_path"], sheet_name=["B_가맹점표본", "D_시장표본"])
    families = load_config(args.families)["families"]
    inactive = {r["query_id"] for r in load_config(bench["query_set"]["inactive_queries_path"])["inactive_queries"]}

    queries = build_service_queries(
        rows, icfg["bundle_priority"], old_benchmark_splits(families, inactive), icfg["exclude_queries"],
        template["B_가맹점표본"], template["D_시장표본"], cfg["split"]["dev_share"], cfg["random_seed"],
    )

    # E는 정말 가맹점이 없는지 판정 전에 볼 수 있게, 상호·취급품목에 그 문자열이 몇 번 나오는지 붙인다
    corpus = pd.read_parquet(bench["corpus_path"], columns=["store_name", "item_text"])
    text = (corpus["store_name"].fillna("") + " " + corpus["item_text"].fillna("")).str.replace(" ", "", regex=False)
    queries["corpus_hits"] = [
        str(int(text.str.contains(q.replace(" ", ""), regex=False).sum())) if b == "E" else ""
        for q, b in zip(queries["query"], queries["bundle"], strict=True)
    ]

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
    logger.info("가정위치 출처: %s / B 지역표현 자동 추출 %d개", queries["location_source"].value_counts().to_dict(),
                (queries["region_text_source"] == "auto").sum())
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return

    out = Path(icfg["output"])
    queries.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    meta = {
        "version": cfg["version"],
        "seed": cfg["random_seed"],
        "dev_share": cfg["split"]["dev_share"],
        "sources": {p: sha256_file(Path(p)) for p in [icfg["writers_completed"], icfg["team_completed"], cfg["output_path"]]},
        "queries": len(queries),
        "active_by_bundle_split": {b: counts.loc[b].to_dict() for b in counts.index},
        "excluded": len(excluded),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s", out)


if __name__ == "__main__":
    main()
