"""서비스셋 주 평가셋(eval_set.csv)을 만든다 — 쿼리 수를 가정한 실제 쿼리 비율에 맞춘 사례 목록. 설명은 docs/SERVICE_QUERYSET.md 1절.

설정 `eval_set`: 묶음 비율(shares), 반경, 해시 salt, 출력 경로.
- 쿼리마다 사례 하나(반경 안 정답이 있는 random, 없으면 anchor).
- split마다 가장 모자란 묶음이 크기를 정한다. 그 묶음을 더 쓰면 셋이 커지고, 이미 뽑힌 쿼리는 그대로 남는다.
- 빠진 사례·쿼리는 지우지 않는다(instances.csv·qrels 그대로). 채점 스크립트가 이 목록으로 거른다(--set main).

다시 실행해도 같은 결과(해시 순). 판정(qrels)이 바뀌거나 쿼리를 더한 뒤 다시 돌린다.

사용법:
    python scripts/build_service_eval_set.py
    python scripts/build_service_eval_set.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import math
from pathlib import Path

import pandas as pd

from store_search_ai.evaluation.service_eval import build_eval_set, instance_qrels, no_answer_counts
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def shortfall(avail: pd.Series, shares: dict[str, float]) -> dict[str, int]:
    """묶음마다, 그 묶음 때문에 다른 묶음이 줄지 않으려면 더 필요한 쿼리 수(0이면 생략)."""

    out = {}
    for b, s in shares.items():
        others = min(avail.get(o, 0) / so for o, so in shares.items() if o != b)
        need = math.ceil(others * s - 1e-9) - int(avail.get(b, 0))
        if need > 0:
            out[b] = need
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    ecfg = cfg["eval_set"]
    bench = load_config(args.benchmark_config)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    instances = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]

    answerable = no_answer_counts(instances, instance_qrels(instances, qrels, coords), ecfg["radius_km"])
    shares = ecfg["shares"]
    picked = build_eval_set(instances, answerable, shares, ecfg["salt"])

    scored = instances[answerable.to_numpy()].drop_duplicates("query_id")
    for split in ("dev", "test"):
        avail = scored[scored["split"] == split]["bundle"].value_counts()
        got = picked[picked["split"] == split]["bundle"].value_counts()
        logger.info("%s: 채점 가능 쿼리 %s → 주 평가셋 %s (계 %d)", split, {b: int(avail.get(b, 0)) for b in shares},
                    {b: int(got.get(b, 0)) for b in shares}, int(got.sum()))
        need = shortfall(avail, shares)
        if need:
            logger.info("  다른 묶음을 줄이지 않으려면 더 필요한 쿼리: %s", need)
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return
    out = Path(ecfg["output"])
    picked.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s (%d개)", out, len(picked))


if __name__ == "__main__":
    main()
