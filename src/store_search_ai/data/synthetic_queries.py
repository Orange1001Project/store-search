"""코퍼스 기반 합성 학습 쿼리(docs/SERVICE_QUERYSET.md 4절).

B 상호명 쿼리는 규칙으로 만든다: 가맹점 이름에서 사용자가 칠 법한 변형(전체 상호, 지점명 뺀 상호, 띄어쓰기 없음,
괄호 안 이름, 브랜드 별칭)을 만들고, 정답은 **쿼리만으로** 정한다 — 쿼리를 정규화한 키와 같은 키를 가진 모든 가맹점.
그래서 같은 쿼리가 어느 가맹점에서 나왔든 정답이 같다('형제상회' → 형제상회 112곳 전부).

A·C(LLM 생성) 입력 표도 여기서 만든다. 생성은 colab/generate_queries.ipynb.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from store_search_ai.data.service_queryset import (
    CORP_PREFIX_RE,
    is_name_only,
    split_items,
)

PAREN_RE = re.compile(r"\([^)]*\)")
PAREN_INNER_RE = re.compile(r"\(([^)]*)\)")
SPACE_RE = re.compile(r"\s+")
LETTER_RE = re.compile(r"[A-Za-z가-힣]")


def clean_name(name: str) -> str:
    """법인 표기 제거 + 공백 정리. 사용자가 칠 '전체 상호'의 기준형."""

    if not isinstance(name, str):
        return ""
    return SPACE_RE.sub(" ", CORP_PREFIX_RE.sub("", name)).strip()


def paren_names(full: str, paren_aliases: list[str]) -> list[str]:
    """괄호 안 이름 중 상호로 쓸 만한 것. 지점명('(용봉점)'), 글자 없는 것('(050)'),
    별칭 표기의 일부('지에스(GS)25'의 GS)는 뺀다."""

    if any(alias in full for alias in paren_aliases):
        return []
    out = []
    for inner in PAREN_INNER_RE.findall(full):
        inner = inner.strip()
        if len(inner) >= 2 and not inner.endswith("점") and LETTER_RE.search(inner):
            out.append(inner)
    return out


def build_alias_table(aliases: dict[str, list[str]]) -> list[tuple[str, str]]:
    """(정규화한 별칭, 정규화한 대표명) 목록. 긴 별칭부터 맞춰 보도록 정렬한다."""

    def norm(text: str) -> str:
        return SPACE_RE.sub("", PAREN_RE.sub("", text)).casefold()

    table = {norm(v): norm(canon) for canon, variants in aliases.items() for v in [canon, *variants]}
    return sorted(table.items(), key=lambda kv: -len(kv[0]))


def canon_key(text: str, alias_table: list[tuple[str, str]]) -> str:
    """쿼리·상호를 비교하는 키: 법인 표기·괄호·공백 제거, 소문자, 앞부분 브랜드 별칭을 대표명으로."""

    if not isinstance(text, str):
        return ""
    key = SPACE_RE.sub("", PAREN_RE.sub("", CORP_PREFIX_RE.sub("", text))).casefold()
    for alias, canon in alias_table:
        if key.startswith(alias):
            return canon + key[len(alias):]
    return key


def strip_branch(name: str, brands: list[str]) -> str:
    """지점명을 뗀 상호. '크린토피아 운남7단지점' → '크린토피아', 'GS25산들점' → 'GS25'(알려진 브랜드가 붙어 쓴 경우).

    떼어 낼 지점명이 없으면 원래 이름을 그대로 돌려준다.
    """

    tokens = name.split()
    if len(tokens) >= 2 and tokens[-1].endswith("점") and len(tokens[-1]) >= 2:
        return " ".join(tokens[:-1])
    for brand in brands:
        if name.startswith(brand) and len(name) > len(brand) + 1 and name.endswith("점"):
            return brand
    return name


def name_variants(name: str, brands: list[str], aliases: dict[str, list[str]]) -> list[tuple[str, str]]:
    """(변형 종류, 쿼리 문자열) 목록. 문자열이 같은 변형은 하나만 남긴다."""

    full = clean_name(name)
    if not full:
        return []
    full_plain = SPACE_RE.sub(" ", PAREN_RE.sub(" ", full)).strip()
    base = strip_branch(full_plain, brands)
    out = [("full", full_plain)]
    if base != full_plain:
        out.append(("no_branch", base))
    if " " in base:
        out.append(("no_space", base.replace(" ", "")))
    paren_aliases = [v for vs in aliases.values() for v in vs if "(" in v]
    out.extend(("paren_inner", inner) for inner in paren_names(full, paren_aliases))
    for canon, variants in aliases.items():
        group = [canon, *variants]
        hit = next((v for v in sorted(group, key=len, reverse=True) if base.startswith(v)), None)
        if hit:
            rest = base[len(hit):]
            out.extend(("alias", v + rest) for v in group if v != hit)
            break
    seen: set[str] = set()
    unique = []
    for kind, text in out:
        if text and text not in seen:
            seen.add(text)
            unique.append((kind, text))
    return unique


def build_name_index(
    corpus: pd.DataFrame, brands: list[str], aliases: dict[str, list[str]]
) -> dict[str, set[str]]:
    """키 → 그 키로 찾아져야 할 doc_id 집합. 가맹점마다 전체 상호·지점명 뺀 상호·괄호 안 이름의 키를 등록한다."""

    alias_table = build_alias_table(aliases)
    paren_aliases = [v for vs in aliases.values() for v in vs if "(" in v]
    index: dict[str, set[str]] = defaultdict(set)
    for doc_id, name in zip(corpus["doc_id"], corpus["store_name"], strict=True):
        full = clean_name(name)
        if not full:
            continue
        full_plain = SPACE_RE.sub(" ", PAREN_RE.sub(" ", full)).strip()
        keys = {canon_key(full, alias_table), canon_key(strip_branch(full_plain, brands), alias_table)}
        keys |= {canon_key(inner, alias_table) for inner in paren_names(full, paren_aliases)}
        for key in keys:
            if key:
                index[key].add(doc_id)
    return index


def category_vocab(corpus: pd.DataFrame, families: list[dict], min_count: int) -> set[str]:
    """업종어 집합(공백 없는 소문자). 상호가 업종어와 같으면 상호명 쿼리가 아니라 업종 쿼리다."""

    counts = Counter(tok for text in corpus["item_text"] for tok in set(split_items(text)))
    vocab = {tok for tok, n in counts.items() if n >= min_count}
    for fam in families:
        vocab |= {fam["family"], *fam["positive_terms"]}
    return {SPACE_RE.sub("", v).casefold() for v in vocab}


def generate_name_queries(
    corpus: pd.DataFrame,
    n_stores: int,
    brands: list[str],
    aliases: dict[str, list[str]],
    vocab: set[str],
    exclude_doc_ids: set[str],
    exclude_brands: list[str],
    many_positives: int,
    seed: int,
) -> pd.DataFrame:
    """가맹점 n_stores곳을 뽑아 상호명 쿼리를 만든다. 쿼리 문자열 하나에 한 행.

    중복은 사용자가 치는 문자열(공백 정리·소문자) 기준으로 뺀다. '차이나 웍 짬뽕'과 '차이나웍짬뽕'은 정답이 같아도
    둘 다 남긴다 — 띄어쓰기·별칭 차이를 견디게 하는 것이 이 데이터의 목적이다.

    빠지는 쿼리: 길이 2 미만, 업종어와 같은 것, 정답에 제외 가맹점이 들어가는 것, 제외 브랜드 키로 시작하는 것.
    """

    alias_table = build_alias_table(aliases)
    index = build_name_index(corpus, brands, aliases)
    excluded_brand_keys = [canon_key(b, alias_table) for b in exclude_brands]

    sampled = corpus.sample(n=min(n_stores, len(corpus)), random_state=np.random.default_rng(seed).integers(2**32))
    rows, seen = [], set()
    for doc_id, name in zip(sampled["doc_id"], sampled["store_name"], strict=True):
        for kind, query in name_variants(name, brands, aliases):
            key = canon_key(query, alias_table)
            surface = SPACE_RE.sub(" ", query).strip().casefold()
            if surface in seen or len(key) < 2 or key in vocab:
                continue
            if any(key.startswith(b) for b in excluded_brand_keys if b):
                continue
            positives = index.get(key, set())
            if not positives or positives & exclude_doc_ids:
                continue
            seen.add(surface)
            rows.append(
                {
                    "query": query,
                    "variant": kind,
                    "source_doc_id": doc_id,
                    "n_positives": len(positives),
                    "many_positives": len(positives) > many_positives,
                    "positive_doc_ids": "|".join(sorted(positives)),
                }
            )
    return pd.DataFrame(rows)


def generation_store_sample(
    corpus: pd.DataFrame,
    n_stores: int,
    generic_items: set[str],
    skip_name_only: bool,
    exclude_doc_ids: set[str],
    seed: int,
) -> pd.DataFrame:
    """A·C LLM 생성 입력 가맹점. 시장유형 비율대로 뽑는다."""

    pool = corpus[~corpus["doc_id"].isin(exclude_doc_ids)]
    if skip_name_only:
        pool = pool[~pool["item_text"].map(lambda s: is_name_only(s, generic_items))]
    rng = np.random.default_rng(seed)
    shares = pool["market_type"].value_counts(normalize=True)
    parts = []
    for market_type, share in shares.items():
        group = pool[pool["market_type"] == market_type]
        quota = min(len(group), round(share * n_stores))
        if quota:
            parts.append(group.sample(n=quota, random_state=rng.integers(2**32)))
    sample = pd.concat(parts, ignore_index=True)
    return sample[["doc_id", "store_name", "item_text", "market_type"]].assign(
        item_text=lambda d: d["item_text"].fillna("")
    )


def fewshot_examples(families: list[dict], inactive_ids: set[str], split: str) -> pd.DataFrame:
    """프롬프트 예시: 지정 split 업종의 활성 쿼리. bundle A=T2·T3·T4, C=T4·T5(상황·목적형)."""

    rows = []
    for fam in families:
        if fam["split"] != split:
            continue
        for i, q in enumerate(fam["queries"], start=1):
            if f"q_{fam['family']}_{i:02d}" in inactive_ids:
                continue
            qtype = q["type"].split()[0]
            bundles = {"T2": "A", "T3": "A", "T4": "AC", "T5": "C"}.get(qtype, "")
            for bundle in bundles:
                rows.append({"bundle": bundle, "family": fam["family"], "type": q["type"], "query": q["text"]})
    return pd.DataFrame(rows)


def template_excluded_doc_ids(template_path: str) -> set[str]:
    """서비스셋 템플릿의 B_가맹점표본 doc_id — 서비스셋 test 상호명 쿼리의 정답 후보라 학습 쿼리에서 뺀다."""

    sample = pd.read_excel(template_path, sheet_name="B_가맹점표본", usecols=["doc_id"])
    return set(sample["doc_id"].dropna().astype(str))
