"""서비스셋 쿼리 직접 작성용 작성자별 xlsx를 만든다. 절차는 docs/QUERY_WRITING_GUIDE.md 1부.

출력(`writers.output_dir`, 기본 data/query/writers/):
  --layout single(기본)  서비스셋_직접작성_v1.xlsx 한 파일 — 시트: 안내_1부(C·E), 안내_2부(A·D), 배정표, 작성자정보, 합계,
                         W1_1부_C_E, W1_2부_A_D, …, W6_2부_A_D
  --layout per-writer    W1_1부_C_E.xlsx(먼저 줌), W1_2부_A_D.xlsx(1부를 낸 뒤 줌), …, 진행자_배정표.xlsx

한 파일을 여러 작성자가 공유해 동시에 쓰면 서로의 쿼리가 보인다(독립 작성 원칙 위반). 작성자에게 나눠 줄 때는
per-writer로 만들거나, 한 파일에서 그 사람 시트만 복사해 준다.
배정은 설정의 seed로 정해져 다시 만들어도 같다. 이미 출력 폴더가 있으면 덮어쓰지 않는다(--force).

사용법:
    python scripts/make_writer_sheets.py
    python scripts/make_writer_sheets.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from store_search_ai.data.writer_sheets import (
    EXTRA_B_GUIDE,
    PART1_GUIDE,
    PART2_GUIDE,
    WRITER_COLUMNS,
    assign_cards,
    assignment_table,
    carry_over_answers,
    deal,
    extra_b_rows,
    part1_rows,
    part2_rows,
    pick_industries,
    pick_unused_stores,
)
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)

WIDTHS = {"작성자": 7, "묶음": 6, "근거ID": 8, "재료": 48, "질의": 26, "의도": 20, "지역표현": 14, "가정위치ID": 10, "작성방식": 9, "비고": 20}
FILL_COLUMNS = {"질의", "의도", "지역표현", "비고"}
FILL = PatternFill("solid", fgColor="FFF7D6")
SINGLE_FILE = "서비스셋_직접작성_v1.xlsx"
EXTRA_C_FILE = "서비스셋_직접작성_v1_추가C.xlsx"
EXTRA_B_FILE = "서비스셋_직접작성_v1_추가B.xlsx"


def write_guide_sheet(writer: pd.ExcelWriter, name: str, guide: list[tuple[str, str]]) -> None:
    pd.DataFrame(guide, columns=["항목", "내용"]).to_excel(writer, sheet_name=name, index=False)
    ws = writer.sheets[name]
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 110
    for cell in ws["B"]:
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def write_input_sheet(writer: pd.ExcelWriter, name: str, rows: pd.DataFrame, bundles: str) -> None:
    rows.to_excel(writer, sheet_name=name, index=False)
    ws = writer.sheets[name]
    ws.freeze_panes = "E2"
    for idx, col in enumerate(WRITER_COLUMNS, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = WIDTHS[col]
        if col in FILL_COLUMNS:   # 작성자가 채울 칸만 색칠
            for r in range(2, len(rows) + 2):
                ws[f"{letter}{r}"].fill = FILL
        if col == "재료":
            for r in range(2, len(rows) + 2):
                ws[f"{letter}{r}"].alignment = Alignment(wrap_text=True, vertical="top")
    letter = get_column_letter(WRITER_COLUMNS.index("묶음") + 1)
    dv = DataValidation(type="list", formula1=f'"{",".join(bundles)}"', allow_blank=False)
    dv.add(f"{letter}2:{letter}{len(rows) + 50}")
    ws.add_data_validation(dv)


def write_facilitator_sheets(writer: pd.ExcelWriter, table: pd.DataFrame, writers: list[str],
                             totals: dict, targets: dict) -> None:
    info = pd.DataFrame({"작성자": writers, "연령대": "", "온누리 사용(자주/가끔/없음)": "", "팀 내외부": "",
                         "1부 배포": "", "1부 회수": "", "2부 배포": "", "2부 회수": "", "비고": ""})
    table.to_excel(writer, sheet_name="배정표", index=False)
    info.to_excel(writer, sheet_name="작성자정보", index=False)
    pd.DataFrame({"묶음": list(totals), "작성 칸": list(totals.values()),
                  "목표": [targets.get(k, "") for k in totals]}).to_excel(writer, sheet_name="합계", index=False)


def write_extra_c(cfg: dict, writers: list[str], out_dir: Path, force: bool) -> None:
    """추가 C 카드 파일: 작성자마다 모든 추가 카드 한 줄씩. 카드ID는 기존 카드 다음 번호부터."""

    start = len(cfg["scenario_cards"]) + 1
    cards = pd.DataFrame({"카드ID": [f"C{start + i:03d}" for i in range(len(cfg["scenario_cards_extra"]))],
                          "상황": cfg["scenario_cards_extra"]})
    path = out_dir / EXTRA_C_FILE
    if path.exists() and not force:
        raise SystemExit(f"{path}이 이미 있습니다(--force).")
    guide = [g for g in PART1_GUIDE if not g[0].startswith("E")]
    out_dir.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        write_guide_sheet(writer, "안내(C)", guide)
        for i, w in enumerate(writers):
            order = cards.sample(frac=1, random_state=cfg["random_seed"] + i).reset_index(drop=True)   # 사람마다 순서만 다르게
            write_input_sheet(writer, f"{w}_추가_C", part1_rows(w, order, 0), "C")
    logger.info("저장: %s (카드 %d장 × 작성자 %d명 = %d줄)", path, len(cards), len(writers), len(cards) * len(writers))


def write_extra_b(cfg: dict, writers: list[str], template: str, out_dir: Path, force: bool) -> None:
    """추가 B 파일(2026-10-26, 주 평가셋 비율 맞추기): 아직 쿼리를 안 쓴 B_가맹점표본 가게를 작성자마다 겹치지 않게 나눈다."""

    path = out_dir / EXTRA_B_FILE
    if path.exists() and not force:
        raise SystemExit(f"{path}이 이미 있습니다(--force).")
    stores = pd.read_excel(template, sheet_name="B_가맹점표본")
    queries = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    used = set(queries["basis_id"])
    per_writer = cfg["writers"]["extra_b_per_writer"]
    picked = pick_unused_stores(stores, used, per_writer * len(writers), cfg["store_sample"]["name_only_share"],
                                cfg["random_seed"] + 3)
    out_dir.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        write_guide_sheet(writer, "안내(B)", EXTRA_B_GUIDE)
        for i, w in enumerate(writers):
            write_input_sheet(writer, f"{w}_추가_B", extra_b_rows(w, picked.iloc[i * per_writer:(i + 1) * per_writer]), "B")
    logger.info("저장: %s (안 쓴 표본 가게 %d개 중 %d개 = 작성자 %d명 × %d, 층 %s)", path,
                (~stores["표본ID"].isin(used)).sum(), len(picked), len(writers), per_writer, picked["층"].value_counts().to_dict())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--template", default=None, help="기본: 설정의 output_path(서비스셋 템플릿)")
    parser.add_argument(
        "--layout", choices=["single", "per-writer"], default="single",
        help="single: 한 파일에 시트로(기본) / per-writer: 작성자별 1부·2부 파일 + 진행자 배정표",
    )
    parser.add_argument("--force", action="store_true", help="출력 폴더가 있어도 덮어쓴다")
    parser.add_argument(
        "--extra-c", action="store_true",
        help="추가 C 카드(설정 scenario_cards_extra)만 담은 파일을 만든다 — 작성자 모두 모든 카드(1부 C만, E 없음)",
    )
    parser.add_argument(
        "--extra-b", action="store_true",
        help="추가 B(안 쓴 B_가맹점표본 가게)만 담은 파일을 만든다 — 주 평가셋 비율 맞추기(설정 writers.extra_b_per_writer)",
    )
    parser.add_argument(
        "--carry-over", default=None,
        help="이전 배정 파일(한 파일 배치)에 이미 쓴 답을 같은 작성자·묶음·근거ID 줄로 옮긴다(예: 작성자 수를 바꿀 때)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    wcfg = cfg["writers"]
    writers = wcfg["ids"]
    seed = cfg["random_seed"]
    template = args.template or cfg["output_path"]
    out_dir = Path(wcfg["output_dir"])
    if args.extra_c:   # 추가 C 파일은 자기 파일만 검사한다(write_extra_c)
        write_extra_c(cfg, writers, out_dir, args.force)
        return
    if args.extra_b:
        write_extra_b(cfg, writers, template, out_dir, args.force)
        return
    single_path = out_dir / wcfg.get("single_file", SINGLE_FILE)
    existing = single_path.exists() if args.layout == "single" else any(out_dir.glob("W*_*.xlsx"))
    if existing and not (args.force or args.dry_run):
        raise SystemExit(f"{out_dir}에 이미 배정 파일이 있습니다. 배포한 파일일 수 있어 덮어쓰지 않습니다(--force).")

    sheets = pd.read_excel(template, sheet_name=["C_상황카드", "A_업종후보", "D_시장표본"])
    cards = sheets["C_상황카드"].set_index("카드ID")
    industries = pick_industries(sheets["A_업종후보"], wcfg["a_industries"])
    markets = sheets["D_시장표본"]

    card_map = assign_cards(list(cards.index), writers, wcfg["card_overlap"], seed)
    per_writer_industries = len(industries) // len(writers)
    industry_map = deal(list(industries.index), writers, per_writer_industries, seed + 1)
    market_map = deal(list(markets.index), writers, wcfg["d_markets_per_writer"], seed + 2)

    files: dict[str, dict[str, pd.DataFrame]] = {}
    for w in writers:
        part1 = part1_rows(w, cards.loc[card_map[w]].reset_index(), wcfg["e_queries_per_writer"])
        part2 = part2_rows(w, industries.loc[industry_map[w]], markets.loc[market_map[w]], wcfg["a_queries_per_industry"])
        files[w] = {"1부": part1, "2부": part2}
        if args.carry_over:
            old = pd.read_excel(args.carry_over, sheet_name=None)
            for part, suffix in [("1부", "1부_C_E"), ("2부", "2부_A_D")]:
                if f"{w}_{suffix}" in old:
                    files[w][part], moved = carry_over_answers(files[w][part], old[f"{w}_{suffix}"])
                    logger.info("%s %s: 이전 답 %d개 옮김", w, part, moved)
        logger.info("%s: 1부 C %d + E %d / 2부 A %d(업종 %d) + D %d", w, (part1["묶음"] == "C").sum(),
                    (part1["묶음"] == "E").sum(), (part2["묶음"] == "A").sum(), per_writer_industries,
                    (part2["묶음"] == "D").sum())
    table = assignment_table(files)
    totals = table.groupby("묶음")["작성 칸 수"].sum().to_dict()
    targets = {k: v["count"] for k, v in cfg["targets"].items()}
    logger.info("묶음별 작성 칸 합계 %s (목표 %s, B는 기존 사람 작성분)", totals, targets)
    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return

    out_dir.mkdir(parents=True, exist_ok=True)
    if args.layout == "single":
        path = single_path
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            write_guide_sheet(writer, "안내_1부(C·E)", PART1_GUIDE)
            write_guide_sheet(writer, "안내_2부(A·D)", PART2_GUIDE)
            write_facilitator_sheets(writer, table, writers, totals, targets)
            for w, parts in files.items():
                write_input_sheet(writer, f"{w}_1부_C_E", parts["1부"], "CE")
                write_input_sheet(writer, f"{w}_2부_A_D", parts["2부"], "AD")
        logger.info("저장: %s (시트: 안내 2 + 진행자 3 + 작성자 %d명 × 2)", path, len(writers))
        return

    for w, parts in files.items():
        for part, guide, bundles, suffix in [("1부", PART1_GUIDE, "CE", "1부_C_E"), ("2부", PART2_GUIDE, "AD", "2부_A_D")]:
            with pd.ExcelWriter(out_dir / f"{w}_{suffix}.xlsx", engine="openpyxl") as writer:
                write_guide_sheet(writer, "안내", guide)
                write_input_sheet(writer, "쿼리입력", parts[part], bundles)
    with pd.ExcelWriter(out_dir / "진행자_배정표.xlsx", engine="openpyxl") as writer:
        write_facilitator_sheets(writer, table, writers, totals, targets)
    logger.info("저장: %s (작성자 %d명 × 2개 + 진행자_배정표.xlsx)", out_dir, len(writers))

if __name__ == "__main__":
    main()
