"""서비스셋 주 평가셋(eval_set.csv)을 만든다 — 쿼리 수를 가정한 실제 쿼리 비율에 맞춘 사례 목록. 설명은 docs/SERVICE_QUERYSET.md 1절.

설정 `eval_set`: 묶음 비율(shares), 묶음 안 층 비율(strata — A head:tail), 반경, 해시 salt, 출력 경로.
- 쿼리마다 사례 하나(반경 안 정답이 있는 random, 없으면 anchor). 이전 셋에 있던 사례는 정답이 남아 있는 한 그대로 쓴다.
- split마다 가장 모자란 묶음이 크기를 정한다. 이미 있는 eval_set.csv의 쿼리·사례를 먼저 남기고(정답이 남아 있는 한),
  나머지는 해시 순으로 채운다. 이전 쿼리가 빠지는 것은 그 묶음 자체가 줄 때뿐이다.
- 빠진 사례·쿼리는 지우지 않는다(instances.csv·qrels 그대로). eval_service_pipeline.py가 이 목록으로 거른다(--set main, 기본).
  score_service_eval.py는 거르지 않고 모든 사례를 채점한다.

결과는 이전 eval_set.csv에 따라 정해진다(같은 입력이면 같은 결과). 판정(qrels)이 바뀌거나 쿼리를 더한 뒤 다시 돌린다.

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

from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    build_eval_set,
    instance_qrels,
    load_bundle_overrides,
    no_answer_counts,
)
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
    # 평가용 묶음(eval_set.bundle_overrides) — 주 평가셋의 묶음 비율은 이 묶음으로 센다
    instances = apply_eval_bundle(instances, load_bundle_overrides(ecfg.get("bundle_overrides")))
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    coords = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "latitude", "longitude", "geo_status"])
    coords = coords[coords["geo_status"] == "VALID"]

    # A head = 기존 벤치마크 업종(작성자 old_benchmark), tail = 사람이 새로 쓴 드문 업종
    instances["stratum"] = ["head" if "old_benchmark" in w else "tail" for w in instances["writers"]]
    answerable = no_answer_counts(instances, instance_qrels(instances, qrels, coords), ecfg["radius_km"])
    shares = ecfg["shares"]
    out = Path(ecfg["output"])
    previous = pd.read_csv(out, encoding="utf-8-sig") if out.exists() else None
    picked = build_eval_set(instances, answerable, shares, ecfg["salt"], previous, ecfg.get("strata"))
    if previous is not None:
        dropped = sorted(set(previous["instance_id"]) - set(picked["instance_id"]))
        added = sorted(set(picked["instance_id"]) - set(previous["instance_id"]))
        logger.info("이전 셋 대비: 빠짐 %d개 %s / 더해짐 %d개", len(dropped), dropped[:10], len(added))

    scored = instances[answerable.to_numpy()].drop_duplicates("query_id")
    for split in ("dev", "test"):
        avail = scored[scored["split"] == split]["bundle"].value_counts()
        got = picked[picked["split"] == split]["bundle"].value_counts()
        logger.info("%s: 채점 가능 쿼리 %s → 주 평가셋 %s (계 %d)", split, {b: int(avail.get(b, 0)) for b in shares},
                    {b: int(got.get(b, 0)) for b in shares}, int(got.sum()))
        for b in ecfg.get("strata") or {}:
            st = instances.set_index("instance_id")["stratum"]
            have = scored[(scored["split"] == split) & (scored["bundle"] == b)]["stratum"].value_counts()
            took = picked[(picked["split"] == split) & (picked["bundle"] == b)]["instance_id"].map(st).value_counts()
            logger.info("  %s 층: 채점 가능 %s → %s", b, have.to_dict(), took.to_dict())
        need = shortfall(avail, shares)
        if need:
            logger.info("  다른 묶음을 줄이지 않으려면 더 필요한 쿼리: %s", need)
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return
    picked.to_csv(out, index=False, encoding="utf-8-sig", lineterminator="\n")
    logger.info("저장: %s (%d개)", out, len(picked))


if __name__ == "__main__":
    main()
