"""서비스형 쿼리셋(service_queryset_v1) 작성 템플릿에 들어갈 참고 표를 만든다.

기존 업종 의도 쿼리셋(query_families_v1)은 업종명을 보고 쓴 쿼리라 상호명·지역·상황 쿼리를 재지 못한다.
이 모듈은 작성자가 쿼리를 쓸 때 볼 재료(빠진 업종 후보, 가맹점 표본, 체인 목록, 시장 표본, 결과 없음 후보)를
코퍼스에서 뽑는다. 쿼리 자체는 사람이 쓴다 — 계획과 원칙은 docs/SERVICE_QUERYSET.md.
"""

from __future__ import annotations

import re
from collections import Counter

import numpy as np
import pandas as pd

ITEM_SPLIT_RE = re.compile(r"[,/·()\[\]\s]+")
CORP_PREFIX_RE = re.compile(r"\(주\)|㈜|주식회사|유한회사")

INPUT_COLUMNS = [
    "작성자",
    "묶음",
    "질의",
    "의도",
    "지역표현",
    "가정위치ID",
    "근거ID",
    "유형",
    "작성방식",
    "비고",
]
"""쿼리입력 시트의 열. 묶음=A~E, 의도=찾는 업종·품목·상호(사람이 짧게), 지역표현=질의 속 지역 말(D만),
가정위치ID=검색한 위치(D_시장표본의 M번호, B는 비워 두면 표본 가맹점 위치), 근거ID=카드·표본·후보 ID,
유형=A에서만 T1~T5(기존 분류), 작성방식=직접/LLM후보."""


def split_items(item_text: str) -> list[str]:
    if not isinstance(item_text, str):
        return []
    return [tok for tok in ITEM_SPLIT_RE.split(item_text) if tok]


def is_name_only(item_text: str, generic_items: set[str]) -> bool:
    """취급품목이 비었거나 업종을 알려 주지 않는 일반어뿐이면 True — 상호명으로만 찾을 수 있는 가맹점."""

    tokens = split_items(item_text)
    return all(tok in generic_items for tok in tokens)


def brand_token(store_name: str) -> str:
    """상호의 첫 토큰(법인 표기 제거). 체인은 보통 '브랜드 지점명' 형태라 첫 토큰이 브랜드다."""

    if not isinstance(store_name, str):
        return ""
    parts = CORP_PREFIX_RE.sub("", store_name).split()
    return parts[0] if parts else ""


def chain_candidates(
    corpus: pd.DataFrame,
    aliases: dict[str, list[str]],
    generic_tokens: list[str],
    common_suffixes: list[str],
    min_count: int,
) -> pd.DataFrame:
    """첫 토큰이 min_count번 이상 나오는 상호를 별칭으로 묶어 센다.

    체인인지 흔한 상호(○○상회)인지는 꼬리말로만 구분한다 — 확정은 작성자가 한다.
    """

    alias_of = {variant: canon for canon, variants in aliases.items() for variant in variants}
    tokens = corpus["store_name"].map(brand_token)
    frame = pd.DataFrame(
        {"token": tokens, "brand": tokens.map(lambda t: alias_of.get(t, t)), "region": corpus["source_region"]}
    )
    frame = frame[(frame["token"] != "") & ~frame["token"].isin(generic_tokens)]

    rows = []
    for brand, group in frame.groupby("brand"):
        if len(group) < min_count:
            continue
        variants = group["token"].value_counts()
        is_common = any(brand.endswith(suffix) for suffix in common_suffixes)
        rows.append(
            {
                "브랜드": brand,
                "구분": "동명 가맹점(흔한 상호)" if is_common else "체인 후보",
                "가맹점수": len(group),
                "시도수": group["region"].nunique(),
                "표기": ", ".join(f"{v}({n})" for v, n in variants.items()),
            }
        )
    out = pd.DataFrame(rows).sort_values(["구분", "가맹점수"], ascending=[False, False], ignore_index=True)
    out.insert(0, "체인ID", [f"CH{i + 1:03d}" for i in range(len(out))])
    return out


def item_gap_candidates(
    corpus: pd.DataFrame,
    covered_terms: set[str],
    generic_items: set[str],
    top_n: int,
) -> pd.DataFrame:
    """기존 업종어(family 이름 + positive_terms)가 취급품목에 안 들어가는 가맹점의 품목 토큰을 센다."""

    items = corpus["item_text"].fillna("")
    covered = items.map(lambda s: any(term in s for term in covered_terms))
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    for item_text, name in zip(items[~covered], corpus.loc[~covered, "store_name"], strict=True):
        for tok in set(split_items(item_text)):
            if tok in generic_items or len(tok) < 2:
                continue
            counts[tok] += 1
            if len(examples.setdefault(tok, [])) < 3:
                examples[tok].append(name)
    rows = [
        {"후보ID": f"A{i + 1:03d}", "구분": "미포함 품목", "업종·품목": tok, "가맹점수": n, "예시 상호": ", ".join(examples[tok])}
        for i, (tok, n) in enumerate(counts.most_common(top_n))
    ]
    return pd.DataFrame(rows)


def family_gap_rows(
    fam_list: pd.DataFrame,
    families: list[dict],
    inactive_ids: set[str],
    thin_max: int,
    start_index: int,
) -> pd.DataFrame:
    """패밀리목록에 있었지만 채택되지 않은 업종 + 질의가 thin_max개 이하인 기존 업종."""

    adopted = {f["family"]: f for f in families}
    rows = []
    for _, fam in fam_list[~fam_list["패밀리"].isin(adopted)].iterrows():
        rows.append(
            {
                "구분": "미채택 업종(패밀리목록)",
                "업종·품목": fam["패밀리"],
                "가맹점수": fam["관련 가맹점"],
                "예시 상호": f"우선순위 {fam['우선순위']}",
            }
        )
    for fam in families:
        active = [
            q for i, q in enumerate(fam["queries"], start=1) if f"q_{fam['family']}_{i:02d}" not in inactive_ids
        ]
        if len(active) <= thin_max:
            rows.append(
                {
                    "구분": f"기존 업종 보강({fam['split']})",
                    "업종·품목": fam["family"],
                    "가맹점수": np.nan,
                    "예시 상호": "현재 질의: " + ", ".join(q["text"] for q in active),
                }
            )
    out = pd.DataFrame(rows)
    out.insert(0, "후보ID", [f"A{start_index + i:03d}" for i in range(len(out))])
    return out


def sample_stores(
    corpus: pd.DataFrame,
    n: int,
    name_only_share: float,
    generic_items: set[str],
    seed: int,
) -> pd.DataFrame:
    """B 묶음용 가맹점 표본. 상호명으로만 찾을 수 있는 가맹점을 name_only_share만큼, 나머지는 시장유형 비율대로."""

    rng = np.random.default_rng(seed)
    valid = corpus[corpus["geo_status"] == "VALID"]
    name_only = valid["item_text"].fillna("").map(lambda s: is_name_only(s, generic_items))

    n_name_only = round(n * name_only_share)
    picked = [valid[name_only].sample(n=n_name_only, random_state=rng.integers(2**32)).assign(층="상호명만")]
    rest = valid[~name_only]
    shares = rest["market_type"].value_counts(normalize=True)
    quotas = (shares * (n - n_name_only)).round().astype(int)
    for market_type, quota in quotas.items():
        if quota:
            pool = rest[rest["market_type"] == market_type]
            picked.append(pool.sample(n=quota, random_state=rng.integers(2**32)).assign(층=f"일반·{market_type}"))
    sample = pd.concat(picked, ignore_index=True)
    out = pd.DataFrame(
        {
            "표본ID": [f"S{i + 1:03d}" for i in range(len(sample))],
            "층": sample["층"],
            "가맹점명": sample["store_name"],
            "취급품목": sample["item_text"].fillna(""),
            "시장명": sample["market_name"],
            "시장유형": sample["market_type"],
            "주소": sample["address"],
            "위도": sample["latitude"],
            "경도": sample["longitude"],
            "doc_id": sample["doc_id"],
        }
    )
    return out


def sigungu(address: str) -> str:
    parts = address.split() if isinstance(address, str) else []
    return parts[1] if len(parts) > 1 else ""


def sample_markets(corpus: pd.DataFrame, n: int, min_per_region: int, min_stores: int, seed: int) -> pd.DataFrame:
    """D 묶음·가정위치용 시장 표본. 시도별 가맹점 수 비율대로 뽑고 시도마다 최소 min_per_region개.

    사용자 분포(인구·검색량)를 모르므로 가맹점 분포를 대신 쓴다 — 로그를 확보하면 그 분포로 바꾼다.
    """

    rng = np.random.default_rng(seed)
    valid = corpus[corpus["geo_status"] == "VALID"]
    markets = (
        valid.groupby(["source_region", "market_name"])
        .agg(
            시장유형=("market_type", "first"),
            시군구=("address", lambda s: sigungu(s.iloc[0])),
            가맹점수=("doc_id", "size"),
            위도=("latitude", "mean"),
            경도=("longitude", "mean"),
            주요품목=("item_text", lambda s: ", ".join(s.dropna().value_counts().index[:5])),
        )
        .reset_index()
    )
    markets = markets[markets["가맹점수"] >= min_stores]
    shares = markets.groupby("source_region")["가맹점수"].sum()
    shares = shares / shares.sum()
    picked = []
    for region, share in shares.sort_index().items():
        pool = markets[markets["source_region"] == region]
        quota = min(len(pool), max(min_per_region, round(share * n)))
        picked.append(pool.sample(n=quota, random_state=rng.integers(2**32)))
    sample = pd.concat(picked, ignore_index=True).rename(columns={"source_region": "시도", "market_name": "시장명"})
    sample.insert(0, "시장ID", [f"M{i + 1:03d}" for i in range(len(sample))])
    return sample[["시장ID", "시도", "시군구", "시장명", "시장유형", "가맹점수", "위도", "경도", "주요품목"]]


def absent_candidate_counts(corpus: pd.DataFrame, words: list[str]) -> pd.DataFrame:
    text = corpus["store_name"].fillna("") + " " + corpus["item_text"].fillna("")
    rows = [{"후보ID": f"E{i + 1:03d}", "질의 후보": w, "코퍼스 출현 수": int(text.str.contains(w, regex=False).sum())}
            for i, w in enumerate(words)]
    out = pd.DataFrame(rows).sort_values("코퍼스 출현 수", ignore_index=True)
    out["판단"] = np.where(out["코퍼스 출현 수"] <= 5, "E로 사용 가능", "가맹점 있음 — E 아님(필요하면 A 후보)")
    return out


def scenario_card_table(cards: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"카드ID": [f"C{i + 1:03d}" for i in range(len(cards))], "상황": cards})


def guide_table(targets: dict, version: str, seed: int) -> pd.DataFrame:
    rows = [
        ("이 파일", f"{version} 작성용. 기존 업종 의도 쿼리셋(queryset_final.xlsx)과 별도 셋이다. 표본 seed {seed}."),
        ("원칙 1", "각자 따로 쓴다. 다른 작성자의 쿼리를 보지 않는다(서로 비슷해지면 실제 분포에서 멀어짐)."),
        ("원칙 2", "실제 앱 검색창에 칠 말 그대로. 짧아도 된다. 오타는 일부러 넣지 않는다."),
        ("원칙 3", "C(상황)는 코퍼스·업종 목록을 보지 말고 카드만 보고 쓴다."),
        ("원칙 4", "LLM으로 만든 후보는 작성방식=LLM후보로 표시한다. test에는 직접 쓴 쿼리 중심으로 넣는다."),
        ("", ""),
    ]
    for key, t in targets.items():
        rows.append((f"묶음 {key}", f"{t['name']} — 목표 {t['count']}개"))
    rows += [
        ("", ""),
        ("A 업종 확장", "A_업종후보에서 업종을 골라 4~5개씩. 유형 열에 T1 정확표기/T2 동의어/T3 개념확장/T4 구어·문장/T5 서비스."),
        ("B 상호명", "B_가맹점표본(S번호) 또는 B_체인목록(CH번호)을 보고 그 가게를 찾을 때 칠 말. 전체 이름, 일부, 브랜드만, 다른 표기(BBQ↔비비큐) 등. 의도 열에 찾는 상호."),
        ("C 상황", "C_상황카드(C번호)를 보고 1~3개. 의도 열에는 쓴 뒤에 '어떤 가게를 기대했는지'를 적는다."),
        ("D 지역+업종", "D_시장표본(M번호)의 지역·시장명 + 업종. 지역표현 열에 질의 속 지역 말, 가정위치ID에 M번호."),
        ("E 결과 없음", "E_결과없음후보에서 '사용 가능'인 것 또는 직접 생각한 것. 온누리 가맹점이 아닐 법한 대상."),
        ("가정위치ID", "검색한 사람이 있다고 가정하는 위치(M번호). B는 비우면 표본 가맹점 위치. A·C·E는 비우면 나중에 자동 배정."),
        ("판정", "사람은 업종·상호 관련성만 판정. 지역 일치는 주소·좌표로 자동 계산한다."),
    ]
    return pd.DataFrame(rows, columns=["항목", "내용"])
