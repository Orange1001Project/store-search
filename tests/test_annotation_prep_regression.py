"""리팩터링 전후로 09_prepare_full_annotations.py의 산출물이 동일한지 확인하는 golden-file
회귀 테스트.

benchmark/storesearch_ko_v1/agreement_report.json, qrels/provisional_v1/qrels_train_provisional.*,
annotations/full_annotation_v1/analysis/*는 리팩터링 전 스크립트가 실제 완료된 애노테이션
(completed/annotation_A_all_completed.csv, annotation_B_val_test_completed.csv - 사람이 직접
판정한 원본, 이 공유 폴더에 그대로 남아있음)으로 만든 진짜 결과물이다. split별 5개 완료
파일은 체크인돼 있지 않지만(SHARE_NOTES.md - split_completed_annotations.py로 그 자리에서
재생성됨, 순수 코드 변환) 이 테스트는 그 변환을 pandas로 직접 재현해서(스크립트 의존 없이)
tmp_path에 쓴 뒤 load_completed()로 읽는다.
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.annotation_prep import (
    build_adjudication_frame,
    build_agreement_report,
    build_full_annotation_summary,
    build_needed_adjudication,
    build_partial_agreement_qrels,
    load_completed,
    pairwise_report,
    split_train_qrels,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPLETED_DIR = (
    REPO_ROOT / "benchmark" / "storesearch_ko_v1" / "annotations" / "full_annotation_v1" / "completed"
)
ANALYSIS_DIR = REPO_ROOT / "benchmark" / "storesearch_ko_v1" / "annotations" / "full_annotation_v1" / "analysis"
BENCHMARK_DIR = REPO_ROOT / "benchmark" / "storesearch_ko_v1"

A_ALL_PATH = COMPLETED_DIR / "annotation_A_all_completed.csv"
B_VAL_TEST_PATH = COMPLETED_DIR / "annotation_B_val_test_completed.csv"

pytestmark = pytest.mark.skipif(
    not A_ALL_PATH.exists() or not B_VAL_TEST_PATH.exists(),
    reason="완료된 애노테이션 원본(completed/*.csv) 없음",
)


def _split_and_write(source_path: Path, splits: list[str], out_dir: Path, prefix: str) -> None:
    df = pd.read_csv(source_path, encoding="utf-8-sig")
    for split in splits:
        df[df["split"] == split].to_csv(
            out_dir / f"{prefix}_{split}_completed.csv", index=False, encoding="utf-8-sig"
        )


def test_prepare_full_annotations_matches_checked_in_golden_files(tmp_path):
    _split_and_write(A_ALL_PATH, ["train", "val", "test"], tmp_path, "annotation_A")
    _split_and_write(B_VAL_TEST_PATH, ["val", "test"], tmp_path, "annotation_B")

    data = {
        "A_train": load_completed(tmp_path / "annotation_A_train_completed.csv"),
        "A_val": load_completed(tmp_path / "annotation_A_val_completed.csv"),
        "A_test": load_completed(tmp_path / "annotation_A_test_completed.csv"),
        "B_val": load_completed(tmp_path / "annotation_B_val_completed.csv"),
        "B_test": load_completed(tmp_path / "annotation_B_test_completed.csv"),
    }

    train = data["A_train"].copy()
    train_qrels, train_usable, _ = split_train_qrels(train)

    val_merged, val_report = pairwise_report(data["A_val"], data["B_val"], "val")
    test_merged, test_report = pairwise_report(data["A_test"], data["B_test"], "test")

    all_adj_visible = build_adjudication_frame(val_merged, test_merged)
    needed = build_needed_adjudication(all_adj_visible)
    summary = build_full_annotation_summary(train, train_usable, val_report, test_report, needed)
    agreement_report = build_agreement_report(val_merged, test_merged, binary_threshold=2)

    golden_agreement = json.loads((BENCHMARK_DIR / "agreement_report.json").read_text(encoding="utf-8"))
    golden_summary = json.loads(
        (ANALYSIS_DIR / "full_annotation_analysis_summary.json").read_text(encoding="utf-8")
    )
    assert agreement_report == golden_agreement
    assert summary == golden_summary

    # 나머지는 실제 CLI가 쓰는 그대로(index=False, utf-8-sig) tmp_path에 저장한 뒤 바이트 단위로
    # 비교한다 - DataFrame을 직접 비교하면 Int64(메모리) vs float64(golden csv 재파싱 시 추론)
    # 같은 dtype 표현 차이가 노이즈로 끼어들기 때문.
    def _write(frame: pd.DataFrame, name: str) -> Path:
        path = tmp_path / name
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def _assert_matches_golden(written: Path, golden: Path) -> None:
        assert written.read_bytes() == golden.read_bytes(), f"{golden.name} 불일치"

    _assert_matches_golden(
        _write(train_qrels, "qrels_train_provisional.csv"),
        BENCHMARK_DIR / "qrels" / "provisional_v1" / "qrels_train_provisional.csv",
    )
    _assert_matches_golden(
        _write(needed, "adjudication_val_test_needed_only.csv"),
        ANALYSIS_DIR / "adjudication_val_test_needed_only.csv",
    )

    for split, frame in [("val", val_merged), ("test", test_merged)]:
        agreed = build_partial_agreement_qrels(frame)
        _assert_matches_golden(
            _write(agreed, f"qrels_{split}_agreed_partial_DO_NOT_SCORE.csv"),
            ANALYSIS_DIR / f"qrels_{split}_agreed_partial_DO_NOT_SCORE.csv",
        )
