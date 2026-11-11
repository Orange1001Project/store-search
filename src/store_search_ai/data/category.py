"""임시 업종(v0, docs/archive/SERVICE_PIPELINE_PLAN.md 11-14) — 취급품목·상호로 가게를 공식 업종 17개 대분류에 붙인다.

규칙(configs/category/taxonomy_v0.yaml)
  - 취급품목을 정규화(소문자, 공백·쉼표·괄호 등 구분자 제거한 문자열 + 구분자로 나눈 단어)하고 업종 키워드가 나온 위치를 모두 찾는다.
    한 글자 키워드('회', '차', '김')는 단어가 정확히 같을 때만(‘자동차’의 ‘차’가 카페가 되지 않게).
  - 다른 키워드 안에 든 짧은 키워드는 버린다('애견미용'의 '미용', '운동화'의 '운동').
  - 대표 업종 = 가장 앞에 나온 키워드(같은 위치면 긴 키워드, 그다음 설정 순서)의 업종. 걸린 업종은 모두 categories에 남긴다.
  - 취급품목에서 못 정하면 상호 끝말·앞말(name_suffixes·name_prefixes), 그래도 없으면 ETC(기타).
오타 자동 교정은 하지 않는다(11-3 — 자모 1글자 차이 후보의 절반이 정상어). 공식 업종 데이터가 오면 이 결과 대신 그 표를 쓴다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

SEP = re.compile(r"[\s,/·()\[\]+.;:&\-]+")


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    keywords: tuple[str, ...]
    name_suffixes: tuple[str, ...] = ()
    name_prefixes: tuple[str, ...] = ()


def load_taxonomy(cfg: dict) -> list[Category]:
    return [Category(c["code"], c["name"], tuple(k.casefold() for k in c.get("keywords", [])),
                     tuple(s.casefold() for s in c.get("name_suffixes", [])), tuple(s.casefold() for s in c.get("name_prefixes", [])))
            for c in cfg["categories"]]


def _hits(text: str, taxonomy: list[Category]) -> list[tuple[int, int, int, str, str]]:
    """(시작, 끝, 설정 순서, 업종 코드, 키워드) — 정규화 문자열 위 위치."""

    words = [w for w in SEP.split(text.casefold()) if w]
    joined = "".join(words)
    starts, pos = [], 0
    for w in words:
        starts.append(pos)
        pos += len(w)
    out = []
    for order, cat in enumerate(taxonomy):
        for kw in cat.keywords:
            if len(kw) == 1:
                out += [(s, s + 1, order, cat.code, kw) for s, w in zip(starts, words, strict=True) if w == kw]
                continue
            i = joined.find(kw)
            while i >= 0:
                out.append((i, i + len(kw), order, cat.code, kw))
                i = joined.find(kw, i + 1)
    # 다른 키워드 안에 든 짧은 키워드는 버린다
    return [h for h in out if not any(o[0] <= h[0] and h[1] <= o[1] and (o[1] - o[0]) > (h[1] - h[0]) for o in out)]


def assign(item_text: str, store_name: str, taxonomy: list[Category]) -> tuple[str, list[str], str]:
    """(대표 업종, 걸린 업종들, 근거 item|name|none). 세부 업종은 assign_detail."""

    return assign_detail(item_text, store_name, taxonomy)[:3]


def assign_detail(item_text: str, store_name: str, taxonomy: list[Category]) -> tuple[str, list[str], str, str]:
    """(대표 업종, 걸린 업종들, 근거, 세부 업종). 세부 업종 = 대표 업종을 정한 키워드('치킨', '국밥', '안경'), 상호로 정했으면 그 끝말."""

    hits = _hits(str(item_text or ""), taxonomy)
    if hits:
        first = min(hits, key=lambda h: (h[0], -(h[1] - h[0]), h[2]))
        cats = sorted({h[3] for h in hits}, key=lambda c: [x.code for x in taxonomy].index(c))
        return first[3], [first[3]] + [c for c in cats if c != first[3]], "item", first[4]
    name = "".join(w for w in SEP.split(str(store_name or "").casefold()) if w)
    for cat in taxonomy:
        hit = next((s for s in cat.name_suffixes if name.endswith(s)), None) or next(
            (p for p in cat.name_prefixes if name.startswith(p)), None)
        if hit:
            return cat.code, [cat.code], "name", hit
    return "ETC", ["ETC"], "none", ""


def label_stores(corpus: pd.DataFrame, taxonomy: list[Category]) -> pd.DataFrame:
    rows = [assign_detail(t, n, taxonomy) for t, n in zip(corpus["item_text"], corpus["store_name"], strict=True)]
    return pd.DataFrame({"doc_id": corpus["doc_id"].to_numpy(), "category": [r[0] for r in rows],
                         "categories": ["|".join(r[1]) for r in rows], "source": [r[2] for r in rows],
                         "subcategory": [r[3] for r in rows]})


__all__ = ["Category", "assign", "assign_detail", "label_stores", "load_taxonomy"]
