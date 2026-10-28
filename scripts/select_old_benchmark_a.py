"""기존 벤치마크 val/test 업종에서 A head 쿼리를 고른다(2026-10-27). 규칙은 service_import.select_old_benchmark_queries.

왜: 서비스셋 A는 기존 셋에 없던 드문 업종(tail)으로만 만들어, 많이 찾는 업종(head)이 빠져 있다. 사람이 쓴 쿼리를 새로 받는 대신
기존 벤치마크 test 업종 28개 → 서비스 test, val 업종 15개 → 서비스 dev로 업종당 최대 2개를 가져온다(train 업종은 v1 학습에 썼으므로 제외).

출력: 설정 import.old_benchmark_a(CSV). import_service_queries.py가 이 파일을 읽어 A 쿼리로 넣고, split은 이 파일의 값을 쓴다.

사용법:
    python scripts/select_old_benchmark_a.py --dry-run
    python scripts/select_old_benchmark_a.py
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from store_search_ai.data.service_import import normalize, select_old_benchmark_queries
from store_search_ai.pipeline.common import load_config

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
    ocfg = cfg["import"]["old_benchmark_a"]
    bench = load_config(args.benchmark_config)
    families = load_config(args.families)["families"]
    inactive = {r["query_id"] for r in load_config(bench["query_set"]["inactive_queries_path"])["inactive_queries"]}
    out = Path(ocfg["path"])
    current = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    # 이미 가져온 old 쿼리는 빼지 않는다(다시 돌려도 같은 결과) — 서비스셋의 다른 쿼리와 겹치는 문자열만 뺀다
    mine = current["writers"].str.contains("old_benchmark", regex=False)
    existing = set(current.loc[~mine, "query"].map(normalize))
    picked = select_old_benchmark_queries(families, inactive, existing, ocfg["split_map"], ocfg["per_family"], ocfg["salt"],
                                           {normalize(x["query"]) for x in ocfg.get("skip", [])}, ocfg.get("intent_overrides"))
    # 앵커 단어(판정 전 anchor 사례용, build_service_instances --add-anchors가 읽음): 쿼리가 취급품목에 5번 이상 나오면 쿼리,
    # 아니면 업종 이름(설정 anchor_overrides가 우선). 자동 규칙은 의도 문장의 일반어를 고르는 일이 있어 업종으로 고정한다.
    corpus = pd.read_parquet(bench["corpus_path"], columns=["item_text", "geo_status"])
    items = corpus.loc[corpus["geo_status"] == "VALID", "item_text"].fillna("").str.replace(" ", "", regex=False)
    over = ocfg.get("anchor_overrides", {})
    picked["anchor_keyword"] = [
        over.get(f, q.replace(" ", "") if items.str.contains(q.replace(" ", ""), regex=False).sum() >= 5 else f)
        for q, f in zip(picked["query"], picked["old_family"], strict=True)]
    logger.info("업종 %d개 → 쿼리 %d개: %s", picked["old_family"].nunique(), len(picked),
                picked.groupby("split").size().to_dict())
    logger.info("형태: %s", picked.groupby(["split", "old_type"]).size().to_dict())
    for (split, fam), g in picked.groupby(["split", "old_family"]):
        logger.info("  %s %s: %s", split, fam, " / ".join(f"{q}[{t}→{k}]" for q, t, k in zip(g["query"], g["old_type"], g["anchor_keyword"], strict=True)))
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    picked.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s", out)


if __name__ == "__main__":
    main()
