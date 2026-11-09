"""브랜드 별칭 사전(X5, docs/SERVICE_PIPELINE_PLAN.md 11-8) — 같은 브랜드의 다른 표기('GS25'·'지에스25', '파리바게뜨'·'파리바게트')를 묶는다.

코퍼스에서 같은 브랜드가 영문·한글·오기로 섞여 있다(GS25 547곳 / 지에스25 613곳, CU 207 / 씨유 768). 한 표기로 검색하면 상호 일치가 다른 표기
지점을 놓쳐 가장 가까운 지점이 빠진다. 자모 한 글자 차이로 자동 교정하면 대부분 다른 가게(대성상회·해성상회)라, 검수한 사전만 쓴다
(검색 엔진 동의어 사전 관행 — Elasticsearch synonyms). 로그가 생기면 로그 기반 교정(Cucerzan & Brill, EMNLP 2004)으로 넓힌다.

파일: configs/service/brand_alias_v1.csv(brand, variant, kind, stores_with_variant, note). 후보는 지점 3곳 이상 브랜드 중 흔한 이름
('○○상회' 등)을 뺀 자모 1글자 변형과 영문 브랜드에서 뽑아 사람이 골랐다.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from store_search_ai.retrieval.fusion import normalize_name

ALIAS_PATH = "configs/service/brand_alias_v1.csv"
SHORT = 3   # 이보다 짧은 표기('cu', '씨유')는 상호 앞부분 일치로만 센다 — 'cu'가 다른 말 속에 든 상호를 잡지 않게


class BrandAliases:
    def __init__(self, table: pd.DataFrame | None = None):
        self.groups: dict[str, frozenset[str]] = {}
        if table is not None:
            for _, g in table.groupby("brand"):
                variants = frozenset(normalize_name(v) for v in g["variant"]) | {normalize_name(g["brand"].iloc[0])}
                for v in variants:
                    self.groups[v] = self.groups.get(v, frozenset()) | variants

    @classmethod
    def load(cls, path: str | Path = ALIAS_PATH) -> BrandAliases:
        return cls(pd.read_csv(path, encoding="utf-8") if Path(path).exists() else None)

    def variants(self, key: str) -> frozenset[str]:
        """정규화한 키와 같은 브랜드의 모든 표기(별칭이 없으면 키 하나). 키 안에 별칭이 든 경우('gs25역삼점')도 찾는다."""

        k = normalize_name(key)
        if k in self.groups:
            return self.groups[k]
        for v, group in self.groups.items():
            if len(v) >= SHORT and v in k:
                return frozenset(k.replace(v, w) for w in group)
        return frozenset({k})


def brand_store(variants: frozenset[str], store_name: str) -> bool:
    """가게가 그 브랜드의 지점인가 — 표기 하나가 상호에 들어 있다(짧은 표기는 상호 앞부분 일치)."""

    n = normalize_name(store_name)
    return any((v in n) if len(v) >= SHORT else n.startswith(v) for v in variants if v)


__all__ = ["ALIAS_PATH", "BrandAliases", "brand_store"]
