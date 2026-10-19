"""서비스셋 쿼리 직접 작성용 작성자별 xlsx를 만든다. 절차는 docs/QUERY_WRITING_GUIDE.md 1부.

출력(`writers.output_dir`, 기본 data/query/writers/):
  W1_1부_C_E.xlsx   먼저 줌 — 안내 + 쿼리입력(배정 카드 22~23줄 + E 4줄)
  W1_2부_A_D.xlsx   1부를 낸 뒤 줌 — 안내 + 쿼리입력(업종 5개 × 5줄 + 시장 9줄)
  ...
  진행자_배정표.xlsx  배정표, 작성자정보(빈 표), 진행 체크
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
    PART1_GUIDE,
    PART2_GUIDE,
    WRITER_COLUMNS,
    assign_cards,
    assignment_table,
    deal,
    part1_rows,
    part2_rows,
    pick_industries,
)
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)

WIDTHS = {"작성자": 7, "묶음": 6, "근거ID": 8, "재료": 48, "질의": 26, "의도": 20, "지역표현": 14, "가정위치ID": 10, "작성방식": 9, "비고": 20}
FILL_COLUMNS = {"질의", "의도", "지역표현", "비고"}
FILL = PatternFill("solid", fgColor="FFF7D6")


def write_writer_file(path: Path, guide: list[tuple[str, str]], rows: pd.DataFrame, bundles: str) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(guide, columns=["항목", "내용"]).to_excel(writer, sheet_name="안내", index=False)
        rows.to_excel(writer, sheet_name="쿼리입력", index=False)
        ws = writer.sheets["안내"]
        ws.column_dimensions["A"].width = 14
        ws.column_dimensions["B"].width = 110
        for cell in ws["B"]:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws = writer.sheets["쿼리입력"]
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--template", default=None, help="기본: 설정의 output_path(서비스셋 템플릿)")
    parser.add_argument("--force", action="store_true", help="출력 폴더가 있어도 덮어쓴다")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cfg = load_config(args.config)
    wcfg = cfg["writers"]
    writers = wcfg["ids"]
    seed = cfg["random_seed"]
    template = args.template or cfg["output_path"]
    out_dir = Path(wcfg["output_dir"])
    if out_dir.exists() and any(out_dir.iterdir()) and not (args.force or args.dry_run):
        raise SystemExit(f"{out_dir}에 이미 파일이 있습니다. 배포한 파일일 수 있어 덮어쓰지 않습니다(--force).")

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
    for w, parts in files.items():
        write_writer_file(out_dir / f"{w}_1부_C_E.xlsx", PART1_GUIDE, parts["1부"], "CE")
        write_writer_file(out_dir / f"{w}_2부_A_D.xlsx", PART2_GUIDE, parts["2부"], "AD")
    info = pd.DataFrame({"작성자": writers, "연령대": "", "온누리 사용(자주/가끔/없음)": "", "팀 내외부": "",
                         "1부 배포": "", "1부 회수": "", "2부 배포": "", "2부 회수": "", "비고": ""})
    with pd.ExcelWriter(out_dir / "진행자_배정표.xlsx", engine="openpyxl") as writer:
        table.to_excel(writer, sheet_name="배정표", index=False)
        info.to_excel(writer, sheet_name="작성자정보", index=False)
        pd.DataFrame({"묶음": list(totals), "작성 칸": list(totals.values()),
                      "목표": [targets.get(k, "") for k in totals]}).to_excel(writer, sheet_name="합계", index=False)
    logger.info("저장: %s (작성자 %d명 × 2개 + 진행자_배정표.xlsx)", out_dir, len(writers))


if __name__ == "__main__":
    main()
