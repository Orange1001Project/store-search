"""보충 pooling 라운드: 특정 쿼리의 pool을 추가 용어로 넓히고, 새 후보만 A/B 판정 → adjudication →
기존 gold에 덧붙인다. 핵심 로직은 src/store_search_ai/data/supplemental_round.py(+ 07/09/10번과 같은
함수)에 있고, 이 스크립트는 인자 파싱·파일 IO·콘솔 출력만 담당한다.

번호가 16인 이유: 01~15를 한 번 다 돈 뒤(최종 qrels까지 나온 뒤) 빠진 정답이 발견됐을 때 쓰는 후속 단계다.

사용 순서 (예: q_수선_01):

  1) 후보 추가 + 판정 시트 생성
     python scripts/16_supplemental_round.py make --round supplement_v1 \
         --query q_수선_01 --terms "수선|옷수선|의류수선|의복수선|옷수리|수선실|세탁" --per-term 10
     → annotations/supplement_v1/annotation_A.csv, annotation_B.csv (val/test 쿼리면 B도)

  2) A, B가 각자 시트를 채워 annotations/supplement_v1/completed/annotation_A_completed.csv,
     annotation_B_completed.csv로 저장

  3) 비교 + 병합
     python scripts/16_supplemental_round.py merge --round supplement_v1
     → A·B 불일치가 있으면 annotations/supplement_v1/analysis/adjudication_needed_only.csv를 만들고 멈춘다.
       adjudication 후 같은 폴더에 adjudication_needed_only_completed.csv로 저장하고 merge를 다시 실행.
     → 다 확정되면 기존 라운드의 analysis/adjudication_val_test_full_completed.csv에 덧붙인다.

  4) python scripts/11_build_qrels.py --adjudication <위 파일>  →  python scripts/12_validate_benchmark.py --stage final
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from store_search_ai.data.adjudication_patch import (
    apply_adjudication_patch,
    build_patch_report,
)
from store_search_ai.data.annotation_pool import (
    accumulate_targeted_candidates,
    build_pool_frame,
    build_pool_stats,
    load_existing_candidates,
    load_pooling_runs,
    merge_pool_history,
    precompute_match_index,
)
from store_search_ai.data.annotation_prep import (
    build_adjudication_frame,
    build_needed_adjudication,
    load_completed,
    pairwise_report,
)
from store_search_ai.data.annotation_sheets import (
    build_annotator_frame,
    write_annotation_file,
)
from store_search_ai.data.supplemental_round import (
    build_supplemental_sheet_rows,
    empty_like,
    merge_into_base_adjudication,
    select_new_pairs,
    target_queries_with_terms,
)
from store_search_ai.pipeline.common import (
    DEFAULT_ANNOTATION_ROUND,
    get_annotation_round_dirs,
    load_active_queries,
    load_config,
)


def _judged_ids(base_annotations_dir: Path) -> set[str]:
    """기존 라운드에서 이미 판정한 judgment_id 전체(A가 train+val+test 전부를 봤으므로 A 시트면 충분)."""

    sheet = base_annotations_dir / "annotation_A_all.csv"
    return set(pd.read_csv(sheet, encoding="utf-8-sig", usecols=["judgment_id"])["judgment_id"])


def make(args, config: dict, benchmark_dir: Path) -> None:
    queries = load_active_queries(benchmark_dir)
    corpus = pd.read_parquet(config["corpus_path"])
    target = target_queries_with_terms(queries, args.query, args.terms.split("|"))
    if (target["split"] == "train").any():
        raise SystemExit("train 쿼리는 아직 지원하지 않습니다(val/test 보충용) — 필요하면 A 단일 판정 경로를 추가할 것.")

    pool_path = benchmark_dir / "candidate_pool_internal.csv"
    candidates = load_existing_candidates(pool_path)
    item_parts_list, store_name_norm = precompute_match_index(corpus)
    accumulate_targeted_candidates(
        candidates, target, corpus, item_parts_list, store_name_norm, args.per_term, args.round
    )
    pool = build_pool_frame(candidates, queries, corpus, args.round)

    base_dir, _ = get_annotation_round_dirs(benchmark_dir, args.base_round)
    new_pairs = select_new_pairs(pool, args.round, args.query, _judged_ids(base_dir))
    if new_pairs.empty:
        raise SystemExit("새 후보가 없습니다 — 다른 용어(--terms)나 더 큰 --per-term을 시도하세요.")

    pool.to_csv(pool_path, index=False, encoding="utf-8-sig", lineterminator="\n")
    run_df = load_pooling_runs(benchmark_dir / "runs" / "pooling", int(config["pooling"]["run_depth"]))
    stats = build_pool_stats(pool, run_df, args.round)
    (benchmark_dir / "pool_stats.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    history_path = benchmark_dir / "pool_history.csv"
    existing_history = pd.read_csv(history_path) if history_path.exists() else None
    merge_pool_history(existing_history, stats, args.round).to_csv(
        history_path, index=False, encoding="utf-8-sig", lineterminator="\n"
    )

    rows = build_supplemental_sheet_rows(new_pairs, queries, args.round)
    out_dir, _ = get_annotation_round_dirs(benchmark_dir, args.round)
    out_dir.mkdir(parents=True, exist_ok=True)
    seed = int(config["annotation"]["random_seed"])
    write_annotation_file(build_annotator_frame(rows, seed, "A"), out_dir / "annotation_A.csv")
    has_double = rows["split"].isin(["val", "test"]).any()
    if has_double:
        b_rows = build_annotator_frame(rows, seed, "B", splits=["val", "test"])
        write_annotation_file(b_rows, out_dir / "annotation_B.csv")

    manifest = {
        "round": args.round,
        "base_round": args.base_round,
        "created_at": datetime.now(UTC).isoformat(),
        "reason": args.reason,
        "queries": args.query,
        "positive_terms": args.terms.split("|"),
        "per_term": args.per_term,
        "new_pairs": len(rows),
        "new_pairs_per_query": rows.groupby("query_id").size().to_dict(),
        "annotators": ["A", "B"] if has_double else ["A"],
        "policy": "기존 판정은 바꾸지 않음. 새 후보만 val/test는 A·B 독립 판정 → 일치 자동 확정 → 불일치 adjudication.",
    }
    (out_dir / "supplemental_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print("========== SUPPLEMENTAL ROUND SHEETS CREATED ==========")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\n다음: A/B가 {out_dir}/annotation_A.csv, annotation_B.csv를 채워 {out_dir}/completed/ 에")
    print("annotation_A_completed.csv, annotation_B_completed.csv로 저장 → merge 실행")


def merge(args, config: dict, benchmark_dir: Path) -> None:
    round_dir, _ = get_annotation_round_dirs(benchmark_dir, args.round)
    a = load_completed(round_dir / "completed" / "annotation_A_completed.csv")
    b = load_completed(round_dir / "completed" / "annotation_B_completed.csv")

    merged = {}
    for split in ("val", "test"):
        a_split, b_split = a[a["split"] == split], b[b["split"] == split]
        if len(a_split) or len(b_split):
            merged[split], report = pairwise_report(a_split, b_split, split)
            print(json.dumps(report, ensure_ascii=False, indent=2))
    reference = next(iter(merged.values()))
    frame = build_adjudication_frame(merged.get("val", empty_like(reference)), merged.get("test", empty_like(reference)))

    analysis_dir = round_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    needed = build_needed_adjudication(frame)
    patch_path = analysis_dir / "adjudication_needed_only_completed.csv"
    if len(needed):
        needed.to_csv(analysis_dir / "adjudication_needed_only.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
        if not patch_path.exists():
            raise SystemExit(
                f"A·B 불일치 {len(needed)}행 → {analysis_dir / 'adjudication_needed_only.csv'}를 adjudication한 뒤 "
                f"{patch_path.name}로 저장하고 merge를 다시 실행하세요."
            )
        patch = pd.read_csv(patch_path, encoding="utf-8-sig")
        frame = apply_adjudication_patch(frame, patch)
        report = build_patch_report(frame, patch)
        if report["unresolved_non_excluded"]:
            raise SystemExit(f"아직 확정 안 된 행이 있습니다: {report['unresolved_rows']}")

    frame["supplemental_round"] = args.round
    frame.to_csv(analysis_dir / "adjudication_full_completed.csv", index=False, encoding="utf-8-sig", lineterminator="\n")

    base_dir, _ = get_annotation_round_dirs(benchmark_dir, args.base_round)
    base_path = base_dir / "analysis" / "adjudication_val_test_full_completed.csv"
    base = pd.read_csv(base_path, encoding="utf-8-sig")
    combined = merge_into_base_adjudication(base, frame)
    combined.to_csv(base_path, index=False, encoding="utf-8-sig", lineterminator="\n")

    print("========== SUPPLEMENTAL ROUND MERGED ==========")
    print(f"추가된 판정 {len(frame)}행 → {base_path} (전체 {len(combined)}행)")
    print(f"다음: python scripts/11_build_qrels.py --adjudication {base_path.as_posix()}")
    print("      python scripts/12_validate_benchmark.py --stage final")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["make", "merge"])
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--round", required=True, help="보충 라운드 이름(예: supplement_v1)")
    parser.add_argument("--base-round", default=DEFAULT_ANNOTATION_ROUND, help="덧붙일 기존 라운드")
    parser.add_argument("--query", action="append", default=[], help="보충할 query_id(여러 번 줄 수 있음) — make 전용")
    parser.add_argument("--terms", default="", help="targeted 채널 용어, |로 구분 — make 전용")
    parser.add_argument("--per-term", type=int, default=10, help="용어당 최대 후보 수 — make 전용")
    parser.add_argument("--reason", default="", help="왜 보충하는지(manifest에 기록) — make 전용")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    if args.command == "make":
        if not args.query:
            raise SystemExit("--query가 필요합니다.")
        make(args, config, benchmark_dir)
    else:
        merge(args, config, benchmark_dir)


if __name__ == "__main__":
    main()
