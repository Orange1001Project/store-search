"""완료된 5개 애노테이션 시트를 검증하고, train은 바로 provisional qrels로, val/test는
A/B 비교 후 일치분 자동 확정 + 불일치분을 adjudication 대상으로 분리한다.

핵심 로직은 src/store_search_ai/data/annotation_prep.py에 있다. 이 스크립트는 인자 파싱,
파일 IO 순서 배치, 콘솔 출력만 담당한다.

사용법:
    python scripts/09_prepare_full_annotations.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from store_search_ai.data.annotation_prep import (
    EXPECTED_FILES,
    build_adjudication_frame,
    build_agreement_report,
    build_full_annotation_summary,
    build_needed_adjudication,
    build_partial_agreement_qrels,
    load_completed,
    pairwise_report,
    split_train_qrels,
    validate_expected_splits,
)
from store_search_ai.pipeline.common import load_config, write_trec_qrels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])

    base = benchmark_dir / "annotations" / "full_annotation_v1"
    completed_dir = base / "completed"
    analysis_dir = base / "analysis"
    qrels_dir = benchmark_dir / "qrels" / "provisional_v1"

    analysis_dir.mkdir(parents=True, exist_ok=True)
    qrels_dir.mkdir(parents=True, exist_ok=True)

    files = {key: completed_dir / filename for key, filename in EXPECTED_FILES.items()}
    missing = [str(path) for path in files.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing completed annotation files:\n" + "\n".join(missing))

    data = {key: load_completed(path) for key, path in files.items()}
    validate_expected_splits(data)

    # ----- Train: single annotation -----
    train = data["A_train"].copy()
    train_qrels, train_usable, train_uncertain_excluded = split_train_qrels(train)

    train_qrels.to_csv(
        qrels_dir / "qrels_train_provisional.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )
    write_trec_qrels(train_qrels, qrels_dir / "qrels_train_provisional.trec")
    train_uncertain_excluded.to_csv(
        analysis_dir / "train_uncertain_excluded.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )

    # ----- Val/Test: A/B pairwise comparison -----
    val_merged, val_report = pairwise_report(data["A_val"], data["B_val"], "val")
    test_merged, test_report = pairwise_report(data["A_test"], data["B_test"], "test")

    all_adj_visible = build_adjudication_frame(val_merged, test_merged)
    all_adj_visible.to_csv(
        analysis_dir / "adjudication_val_test_full.csv", index=False, encoding="utf-8-sig", lineterminator="\n"
    )

    needed = build_needed_adjudication(all_adj_visible)
    needed.to_csv(
        analysis_dir / "adjudication_val_test_needed_only.csv",
        index=False, encoding="utf-8-sig", lineterminator="\n",
    )

    # Partial agreement qrels are diagnostic only.
    for split, frame in [("val", val_merged), ("test", test_merged)]:
        agreed = build_partial_agreement_qrels(frame)
        agreed.to_csv(
            analysis_dir / f"qrels_{split}_agreed_partial_DO_NOT_SCORE.csv",
            index=False, encoding="utf-8-sig", lineterminator="\n",
        )

    summary = build_full_annotation_summary(train, train_usable, val_report, test_report, needed)
    (analysis_dir / "full_annotation_analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    threshold = int(config["relevance"]["binary_threshold"])
    agreement_report = build_agreement_report(val_merged, test_merged, threshold)
    (benchmark_dir / "agreement_report.json").write_text(
        json.dumps(agreement_report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    print("========== FULL ANNOTATION PREP COMPLETE ==========")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
