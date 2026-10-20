"""서비스셋 쿼리를 사람이 직접 쓸 때 작성자마다 나눠 줄 파일의 내용을 만든다(docs/QUERY_WRITING_GUIDE.md 1부).

작성자별로 파일 두 개를 만든다. 1부(C 상황·E 결과 없음)를 끝낸 뒤 2부(A 업종·D 지역)를 준다 — 업종·시장 목록을 먼저 보면
그 단어에 끌려가기 때문이다. 배정은 seed로 정해져 다시 만들어도 같다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

WRITER_COLUMNS = ["작성자", "묶음", "근거ID", "재료", "질의", "의도", "지역표현", "가정위치ID", "작성방식", "비고"]
"""작성자 파일의 쿼리입력 열. `재료`는 읽기용(카드 문장·업종·시장)이고, 작성자는 `질의`·`의도`(D는 `지역표현`도)를 채운다."""

COMMON_RULES = [
    ("이 작업은", "온누리상품권 앱·지도에서 가맹점을 찾을 때 실제로 칠 검색어를 모으는 일입니다. 시험이 아닙니다. 평소 휴대폰으로 검색하듯 쓰세요."),
    ("규칙 1", "ChatGPT 같은 AI, 검색 엔진, 지도 앱을 보지 마세요. 머릿속에서 나온 말이어야 합니다."),
    ("규칙 2", "다른 작성자와 상의하지 마세요. 끝날 때까지 서로의 쿼리를 보지 않습니다."),
    ("규칙 3", "오타를 일부러 넣지 마세요. 띄어쓰기는 평소 습관대로(떡볶이집 / 떡볶이 집 둘 다 괜찮음)."),
    ("규칙 4", "한 번 쓴 것은 고치지 마세요."),
    ("규칙 5", "대부분 2~10자, 길어도 20자 안쪽. 평소 문장으로 검색한다면 문장도 괜찮습니다."),
    ("칸", "질의 = 검색창에 칠 말 그대로 / 의도 = 쓰고 나서, 어떤 가게가 나오길 기대했는지 짧게(예: 구두 수선집)"),
]

PART1_GUIDE = COMMON_RULES + [
    ("C 상황 (먼저)", "재료 칸의 상황에 놓인 나를 떠올리고, 휴대폰을 꺼내 처음 치는 말 하나를 질의 칸에 씁니다. 같은 상황에서 결이 다른 검색어가 또 떠오르면 같은 근거ID로 줄을 하나 더 만들어 씁니다(말만 살짝 바꾼 것은 X)."),
    ("", "업종 이름이 떠오르면 그대로 써도 됩니다(세탁소). 물건·하려는 일·문제로 써도 됩니다(패딩 세탁). 상황 문장을 그대로 옮기지는 마세요."),
    ("예", "구두 뒤축이 다 닳았다 → 좋음: 구두 굽 수선 / 피함: 구두 뒤축이 다 닳았을 때 가는 곳(카드 문장을 옮김)"),
    ("예", "비 오는 날 저녁, 뜨끈한 국물이 당긴다 → 좋음: 칼국수, 국밥집 / 피함: 비 오는 날 국물 음식점 추천(다듬은 문장)"),
    ("E 결과 없음", "온누리 앱에서 누군가 쳐 볼 법하지만 전통시장·상점가 가맹점은 아닐 것 같은 것(대형 업체, 공공기관, 앱 기능 등). 확실하지 않아도 됩니다."),
    ("다 쓰면", "같은 말을 조금만 바꿔 여러 번 쓰지 않았는지, 모든 줄에 의도를 적었는지 확인하고 진행자에게 냅니다. 그다음 2부 파일을 받습니다."),
]

PART2_GUIDE = COMMON_RULES + [
    ("A 업종", "업종마다 5줄. 서로 다른 식으로 씁니다: 그 업종을 부르는 말 / 다른 말·더 넓은 말 / 구체적인 상품·서비스 / 말하듯."),
    ("예", "보청기 → 보청기 가게, 청각 보조기, 보청기 배터리, 귀 잘 안 들릴 때, 보청기 맞추는 곳"),
    ("", "5개 중 2개 이상은 업종 이름이 들어가지 않게. '~추천'·지역 이름은 붙이지 않습니다. 잘 모르는 업종은 아는 만큼만(3개도 괜찮음), 지어내지 마세요."),
    ("D 지역+업종", "그 시장 근처에 있거나 거기 갈 계획인 나를 떠올리고 지역 이름을 넣어 검색합니다(망원시장 떡집, 소래포구 꽃게, 수원 순대)."),
    ("", "지역은 시장 이름·동네·역·구 중 아는 것으로. 업종은 재료의 주요품목에서 골라도 되고 다른 것도 됩니다. 앞에 써도 뒤에 써도 됩니다."),
    ("", "질의 속 지역 부분을 지역표현 칸에 그대로 복사합니다(가정위치ID는 미리 채워져 있음)."),
    ("다 쓰면", "모든 줄에 의도를 적었는지, D의 지역표현을 채웠는지 확인하고 진행자에게 냅니다."),
]


def assign_cards(card_ids: list[str], writers: list[str], overlap: int, seed: int) -> dict[str, list[str]]:
    """카드마다 서로 다른 작성자 overlap명. 카드 순서를 섞은 뒤 k번째 카드를 작성자 k, k+1, …(순환)에게 준다.

    연속한 카드가 서로 다른 작성자 조합을 받아 같은 몇 명끼리만 묶이지 않는다. 1인 배정 수는 카드 수가 작성자 수로
    나눠떨어지지 않으면 조금 차이 난다(45장 × 3명 / 6명 → 21~24장).
    """

    if overlap > len(writers):
        raise ValueError("card_overlap이 작성자 수보다 클 수 없습니다")
    order = list(np.random.default_rng(seed).permutation(card_ids))
    out: dict[str, list[str]] = {w: [] for w in writers}
    for k, card in enumerate(order):
        for j in range(overlap):
            out[writers[(k + j) % len(writers)]].append(card)
    return out


def deal(items: list, writers: list[str], per_writer: int, seed: int) -> dict[str, list]:
    """items를 섞어 작성자마다 per_writer개씩 겹치지 않게 나눈다."""

    need = per_writer * len(writers)
    if len(items) < need:
        raise ValueError(f"재료가 부족합니다: {len(items)}개 < {need}개")
    order = list(np.random.default_rng(seed).permutation(len(items)))[:need]
    return {w: [items[i] for i in order[n * per_writer:(n + 1) * per_writer]] for n, w in enumerate(writers)}


def _row(writer: str, bundle: str, basis: str = "", material: str = "", location: str = "") -> dict:
    row = dict.fromkeys(WRITER_COLUMNS, "")
    row.update({"작성자": writer, "묶음": bundle, "근거ID": basis, "재료": material, "가정위치ID": location, "작성방식": "직접"})
    return row


def part1_rows(writer: str, cards: pd.DataFrame, e_count: int) -> pd.DataFrame:
    rows = [_row(writer, "C", r["카드ID"], r["상황"]) for _, r in cards.iterrows()]
    rows += [_row(writer, "E") for _ in range(e_count)]
    return pd.DataFrame(rows, columns=WRITER_COLUMNS)


def part2_rows(writer: str, industries: pd.DataFrame, markets: pd.DataFrame, per_industry: int) -> pd.DataFrame:
    rows = [
        _row(writer, "A", r["후보ID"], r["업종·품목"])
        for _, r in industries.iterrows()
        for _ in range(per_industry)
    ]
    rows += [
        _row(writer, "D", r["시장ID"], f"{r['시도']} {r['시군구']} {r['시장명']} (주요품목: {r['주요품목']})", r["시장ID"])
        for _, r in markets.iterrows()
    ]
    return pd.DataFrame(rows, columns=WRITER_COLUMNS)


def pick_industries(candidates: pd.DataFrame, names: list[str]) -> pd.DataFrame:
    """A_업종후보에서 이름으로 고른다. 같은 이름이 여러 구분에 있으면(미채택 업종과 미포함 품목 모두 '태권도') 앞의 것."""

    missing = [n for n in names if n not in set(candidates["업종·품목"])]
    if missing:
        raise ValueError(f"A_업종후보에 없는 업종: {missing}")
    first = candidates.drop_duplicates("업종·품목").set_index("업종·품목")
    return first.loc[names].reset_index()


def assignment_table(writer_files: dict[str, dict[str, pd.DataFrame]]) -> pd.DataFrame:
    """진행자용 배정표: 작성자 × 묶음 × 근거ID(중복 행은 하나로) + 개수."""

    frames = [df for parts in writer_files.values() for df in parts.values()]
    table = pd.concat(frames, ignore_index=True)
    return (
        table.groupby(["작성자", "묶음", "근거ID", "재료"], sort=False, dropna=False)
        .size()
        .rename("작성 칸 수")
        .reset_index()
    )


ANSWER_COLUMNS = ["질의", "의도", "지역표현", "비고"]


def carry_over_answers(new_rows: pd.DataFrame, old_rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """이전 배정 파일에 작성자가 쓴 답을 새 배정 시트로 옮긴다. (묶음, 근거ID)가 같은 줄끼리 순서대로 맞춘다.

    E처럼 근거ID가 없는 줄은 묶음 안에서 순서대로 맞춘다. 새 시트에 자리가 모자라면(같은 카드에 두 줄을 썼던 경우 등)
    줄을 덧붙여 답을 잃지 않는다. 돌려주는 값: (답을 채운 새 시트, 옮긴 답 수)
    """

    def key(frame: pd.DataFrame) -> pd.Series:
        return frame["묶음"].astype(str) + "|" + frame["근거ID"].fillna("").astype(str)

    answers = old_rows[ANSWER_COLUMNS].fillna("").astype(str).apply(lambda col: col.str.strip())
    filled = old_rows[(answers != "").any(axis=1)].copy()
    out = new_rows.copy().reset_index(drop=True)
    out_keys = key(out)
    used: set[int] = set()
    extra = []
    for _, row in filled.assign(_key=key(filled)).iterrows():
        slots = [i for i in out.index[out_keys == row["_key"]] if i not in used]
        if slots:
            i = slots[0]
            used.add(i)
            for col in ANSWER_COLUMNS:
                out.loc[i, col] = row[col] if pd.notna(row[col]) else ""
        else:
            new = {c: row.get(c, "") for c in WRITER_COLUMNS}
            extra.append({c: ("" if pd.isna(v) else v) for c, v in new.items()})
    if extra:
        out = pd.concat([out, pd.DataFrame(extra, columns=WRITER_COLUMNS)], ignore_index=True)
    return out, len(filled)
