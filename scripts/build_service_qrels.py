"""서비스셋 판정 라운드를 합쳐 qrels를 만든다. 규칙은 src/store_search_ai/data/service_qrels.py 머리말.

라운드마다(benchmark/service_ko_v1/annotations/<round>/)
  - 입력: annotation_<판정자>_completed.csv (판정자 이름은 파일 이름에서 읽음)
  - 조정: analysis/adjudication_needed.csv를 만든다 → 사람이 final_relevance를 채워 analysis/adjudication_completed.csv로
    저장하면 다음 실행부터 반영된다(빈칸 = gold 제외).
출력(모든 라운드 합침)
  - <benchmark_dir>/qrels.csv            query_id, doc_id, relevance — 확정된 판정만
  - <benchmark_dir>/qrels_status.json    라운드별 판정 수, 조정 대상·미확정 수, 판정자 일치도(이중 판정 쌍)

사용법:
    python scripts/build_service_qrels.py
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd
from sklearn.metrics import cohen_kappa_score

from store_search_ai.data.service_qrels import (
    BINARY_THRESHOLD,
    adjudication_sheet,
    apply_adjudication,
    build_qrels,
    merge_judgments,
)
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def agreement(merged: pd.DataFrame, names: list[str]) -> dict:
    if len(names) < 2:
        return {}
    cols = [f"relevance_{n}" for n in names[:2]]
    both = merged.dropna(subset=cols)
    if both.empty:
        return {}
    x, y = both[cols[0]].astype(int), both[cols[1]].astype(int)
    return {
        "pairs_scored_by_both": len(both),
        "exact_agreement": round(float((x == y).mean()), 4),
        "binary_agreement": round(float(((x >= BINARY_THRESHOLD) == (y >= BINARY_THRESHOLD)).mean()), 4),
        "binary_kappa": round(float(cohen_kappa_score(x >= BINARY_THRESHOLD, y >= BINARY_THRESHOLD)), 4),
        "quadratic_weighted_kappa": round(float(cohen_kappa_score(x, y, weights="quadratic")), 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    bdir = Path(load_config(args.config)["judging"]["benchmark_dir"])
    all_qrels, status = [], {}
    for round_dir in sorted(p for p in (bdir / "annotations").iterdir() if (p / "pool_manifest.json").exists()):
        files = sorted(round_dir.glob("annotation_*_completed.csv"))
        if not files:
            logger.info("%s: 완료 시트 없음 — 건너뜀", round_dir.name)
            continue
        sheets = {f.name.removeprefix("annotation_").removesuffix("_completed.csv"): pd.read_csv(f, encoding="utf-8-sig")
                  for f in files}
        merged = merge_judgments(sheets)
        analysis = round_dir / "analysis"
        analysis.mkdir(exist_ok=True)
        done = analysis / "adjudication_completed.csv"
        adjudicated = pd.read_csv(done, encoding="utf-8-sig") if done.exists() else None
        if adjudicated is None:
            sheet = adjudication_sheet(merged)
            sheet.to_csv(analysis / "adjudication_needed.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
            logger.info("%s: 조정 대상 %d쌍 → %s (final_relevance를 채워 adjudication_completed.csv로 저장)",
                        round_dir.name, len(sheet), analysis / "adjudication_needed.csv")
        final = apply_adjudication(merged, adjudicated)
        qrels = build_qrels(final)
        all_qrels.append(qrels)
        pending = int((final["reason"] != "").sum() - final["adjudicated"].sum())
        status[round_dir.name] = {
            "annotators": sorted(sheets),
            "pairs": len(final),
            "qrels_rows": len(qrels),
            "needs_adjudication": int((final["reason"] != "").sum()),
            "adjudication_pending": pending,
            "excluded_from_gold": int(final["exclude_from_gold"].sum()),
            "reasons": final.loc[final["reason"] != "", "reason"].value_counts().to_dict(),
            "agreement": agreement(merged, sorted(sheets)),
        }
        logger.info("%s: 확정 %d / %d쌍, 조정 대기 %d", round_dir.name, len(qrels), len(final), pending)

    qrels = pd.concat(all_qrels, ignore_index=True)
    dup = qrels.duplicated(["query_id", "doc_id"], keep=False)
    if dup.any():
        raise SystemExit(f"라운드 사이에 같은 (쿼리, 가맹점)이 두 번 판정됐습니다: {int(dup.sum())}행")
    qrels.to_csv(bdir / "qrels.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (bdir / "qrels_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s (%d행, 쿼리 %d개)", bdir / "qrels.csv", len(qrels), qrels["query_id"].nunique())


if __name__ == "__main__":
    main()
