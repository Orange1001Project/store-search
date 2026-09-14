"""data/query/queryset_final.xlsx (팀 3안을 합친 최종 쿼리 시트)를
configs/benchmark/query_families_v1.yaml로 변환한다.

파이프라인 번호가 없는 이유: 05_init_benchmark.py *이전*에 한 번(또는 xlsx가 다시
바뀔 때마다) 사람이 검토 후 실행하는 저작 도구이며, 01~18 실행 순서에는 속하지
않는다. 실행 후에는 그대로 05_init_benchmark.py부터 다시 돌리면 된다.

xlsx 시트 구성(팀이 만든 그대로):
  - 통합질의: 질의, 패밀리, 대분류, 유형(T1~T6), 태그, 출처, 합의, 원본유형,
    현행 결과, 관련 가맹점, 함정
  - 패밀리목록: 패밀리, 대분류, 우선순위(필수/권장/보류), ...

이 스크립트가 하는 일과 이유:
  1. **548개 질의를 전부 살린다**(팀 결정 — family당 variant 최소 개수 제한 없음.
     `05_init_benchmark.py`도 이에 맞춰 최소 1개로 완화했다).
  2. `RECLASSIFY_QUERIES`에 정의된 행은 패밀리를 재배정한다: (a) 원본유형 태그로
     보아 병합 중 다른 family에 잘못 들어간 것이 명백한 행(예: "일본 음식 먹을
     곳"이 한식에 잘못 들어감), (b) 원래 패밀리가 "(미판정)"이던 5행 — 이 중
     3개는 원본유형/함정 힌트로 기존 family에 대응시켰고, 나머지 2개("먹거리",
     "명절 선물세트")는 특정 업종 하나로 좁혀지지 않는 진짜 복합 질의라 새
     family `복합`으로 묶었다. **이 판단은 자동 추론이므로 팀이 한 번 검토할 것.**
  3. 기존 configs/benchmark/query_families_v1.yaml에 이미 있던 family는 원본유형의
     영문 slug로 대응시켜 **기존 split을 그대로 물려받는다**(회귀 방지). 대응되는
     slug가 없는(완전 신규) family만 대분류별 균형 + 무작위로 새 split을 배정한다.
  4. intent_definition은 "{대분류} 중 '{family}'을(를) 판매·제공하는 매장"으로
     초안만 생성한다 — 팀 검토 전 placeholder임을 스크립트 실행 로그에 남긴다.
  5. positive_terms = 그 family의 T1(정확표기)+T2(동의어) 질의 텍스트,
     boundary_terms = 그 family 행들의 '함정' 컬럼 값(콤마 분리, 중복 제거).
     **둘 다 pooling 후보 발굴에만 쓰이고 relevance 판정에는 영향 없음**
     (docs/EXTENDING_DATA.md 참고) — 다소 거칠어도 안전하다.

사용법:
    python scripts/import_queryset_xlsx.py
    python scripts/import_queryset_xlsx.py --input data/query/queryset_final.xlsx \
        --output configs/benchmark/query_families_v1.yaml --dry-run
"""

from __future__ import annotations

import argparse
import random
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import yaml

# 재배정이 필요한 행: (질의 텍스트) -> (정정 후 family, 사유)
RECLASSIFY_QUERIES: dict[str, tuple[str, str]] = {
    # 원본유형 태그로 보아 병합 중 다른 family로 잘못 들어간 것이 명백한 행
    "일본 음식 먹을 곳": ("일식", "원본유형=japanese_food인데 한식에 들어감"),
    "기름 넣는 곳": ("주유소", "원본유형=gas_station인데 식자재에 들어감"),
    "기름 넣으러 갈 데": ("주유소", "원본유형=gas_station인데 식자재에 들어감"),
    "차에 기름 넣을 수 있는 곳": ("주유소", "원본유형=gas_station인데 식자재에 들어감"),
    # 원래 패밀리가 "(미판정)"이던 5행 — 기존 family로 대응 가능한 것
    "배우러 다니는 곳": ("교육", "원본유형=academy"),
    "금 팔러 가는 곳": ("귀금속", "함정=액세서리(구분 대상)로 보아 금 매입/귀금속 업종 추정"),
    "김장 재료 사는 곳": ("야채", "함정=김치 완제품(구분 대상)으로 보아 김장 재료(채소) 구매처 추정"),
    # 특정 업종 하나로 좁혀지지 않는 진짜 복합 질의 — 새 family로 분리
    "먹거리": ("복합", "특정 업종 하나로 안 좁혀지는 포괄 질의"),
    "명절 선물세트": ("복합", "특정 업종 하나로 안 좁혀지는 포괄 질의(과일/정육/건강식품 등 다양)"),
}

# 원본유형 slug가 둘 이상의 서로 다른 family에 걸쳐 나타나 어느 쪽이 맞는지
# 스크립트가 자동으로 판단할 수 없는 경우 — split 상속에 쓰지 않는다.
# (돈가스: 양식/일식 둘 다에 실제로 존재 — 병합 오류가 아니라 팀이 의도적으로
#  두 카테고리 모두에 넣은 것으로 보여 그대로 둔다)
AMBIGUOUS_SLUGS = {"pork_cutlet"}

RANDOM_SEED = 20260831  # configs/benchmark/storesearch_ko_v1.yaml과 동일
NEW_QUERY_SET_VERSION = "query_set_v004"

BATCHIM_JOSA = {True: "을", False: "를"}


def has_batchim(word: str) -> bool:
    ch = word[-1]
    if not ("가" <= ch <= "힣"):
        return False
    return (ord(ch) - ord("가")) % 28 != 0


def build_intent_definition(family: str, category: str) -> str:
    josa = BATCHIM_JOSA[has_batchim(family)]
    return f"{category} 중 '{family}'{josa} 판매·제공하는 매장"


def infer_slug_family_map(queries: pd.DataFrame) -> dict[str, str]:
    """원본유형에서 영문 slug -> 한글 family 대응을 뽑는다. 불명확하면 제외."""

    pairs: dict[str, set[str]] = defaultdict(set)
    for _, row in queries.iterrows():
        match = re.match(r"^([a-z_]+)\s*/", str(row["원본유형"]))
        if not match:
            continue
        pairs[match.group(1)].add(row["패밀리"])

    clean = {}
    for slug, families in pairs.items():
        if slug in AMBIGUOUS_SLUGS:
            continue
        if len(families) == 1:
            clean[slug] = next(iter(families))
    return clean


def assign_fresh_splits(
    families_by_category: dict[str, list[str]],
    train_ratio: float,
    val_ratio: float,
    rng: random.Random,
) -> dict[str, str]:
    """대분류별로 섞은 뒤 비율대로 train/val/test를 배정한다(카테고리 쏠림 방지)."""

    assignment: dict[str, str] = {}
    for category, families in families_by_category.items():
        families = sorted(families)
        rng.shuffle(families)
        n = len(families)
        n_train = round(n * train_ratio)
        n_val = round(n * val_ratio)
        for i, fam in enumerate(families):
            if i < n_train:
                assignment[fam] = "train"
            elif i < n_train + n_val:
                assignment[fam] = "val"
            else:
                assignment[fam] = "test"
    return assignment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/query/queryset_final.xlsx")
    parser.add_argument("--output", default="configs/benchmark/query_families_v1.yaml")
    parser.add_argument(
        "--existing-families",
        default="configs/benchmark/query_families_v1.yaml",
        help="split 상속 기준이 될 현재 yaml (보통 --output과 동일 파일)",
    )
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 요약만 출력")
    args = parser.parse_args()

    with open(args.existing_families, encoding="utf-8") as f:
        existing = yaml.safe_load(f)
    existing_split_by_family = {fam["family"]: fam["split"] for fam in existing["families"]}

    xls = pd.ExcelFile(args.input)
    queries = xls.parse("통합질의")
    fam_list = xls.parse("패밀리목록")

    total_rows = len(queries)

    reclass_mask = queries["질의"].isin(RECLASSIFY_QUERIES)
    for query_text, (new_family, reason) in RECLASSIFY_QUERIES.items():
        row_mask = queries["질의"] == query_text
        if row_mask.any():
            old_family = queries.loc[row_mask, "패밀리"].iloc[0]
            print(f"[재배정] '{query_text}': {old_family} -> {new_family} ({reason})")
        else:
            print(f"[경고] RECLASSIFY_QUERIES에 있는 '{query_text}'를 xlsx에서 찾지 못함")
    queries.loc[reclass_mask, "패밀리"] = (
        queries.loc[reclass_mask, "질의"].map(lambda q: RECLASSIFY_QUERIES[q][0])
    )

    stray_unassigned = queries[queries["패밀리"] == "(미판정)"]
    if len(stray_unassigned):
        raise ValueError(
            f"RECLASSIFY_QUERIES에 없는 '(미판정)' 행이 남아있습니다: "
            f"{stray_unassigned['질의'].tolist()} — 재배정 규칙을 추가하세요."
        )

    print(f"\n[포함] 전체 질의 {total_rows}개 전부 유지 (family당 최소 variant 제한 없음)")

    included_families = sorted(queries["패밀리"].unique())

    # split 상속 우선순위: (1) 기존 yaml에 같은 한글 family 이름이 이미 있으면 그대로
    # (재실행해도 기존 배정이 안 흔들림), (2) 없으면 원본유형 영문 slug로 대응 시도
    # (완전히 새로 만드는 첫 실행 등, 기존 yaml이 영문 slug 체계일 때 대비).
    inherited_splits: dict[str, str] = {}
    for fam in included_families:
        if fam in existing_split_by_family:
            inherited_splits[fam] = existing_split_by_family[fam]

    slug_family_map = infer_slug_family_map(queries)
    for slug, korean_family in slug_family_map.items():
        if korean_family not in inherited_splits and slug in existing_split_by_family:
            inherited_splits[korean_family] = existing_split_by_family[slug]
    category_by_family = fam_list.set_index("패밀리")["대분류"].to_dict()

    needs_fresh = [f for f in included_families if f not in inherited_splits]
    families_by_category: dict[str, list[str]] = defaultdict(list)
    for fam in needs_fresh:
        families_by_category[category_by_family.get(fam, "기타")].append(fam)

    rng = random.Random(RANDOM_SEED)
    # 기존 36개 family 비율(train 15/val 8/test 13 ≈ 42%/22%/36%)과 비슷하게 맞춘다.
    fresh_splits = assign_fresh_splits(families_by_category, train_ratio=0.42, val_ratio=0.22, rng=rng)

    print(f"\n[split 상속] 기존 yaml에서 물려받은 family {len(inherited_splits)}개")
    print(f"[split 신규배정] 대분류별 균형+무작위로 새로 배정한 family {len(fresh_splits)}개")

    final_split = {**fresh_splits, **inherited_splits}
    split_counts = pd.Series(final_split).value_counts()
    print(f"[split 분포] {split_counts.to_dict()}")

    out_families = []
    for fam in included_families:
        sub = queries[queries["패밀리"] == fam]
        category = category_by_family.get(fam, "기타")

        positive_terms = sorted(
            set(sub.loc[sub["유형"].isin(["T1 정확표기", "T2 동의어"]), "질의"].tolist())
        )
        boundary_terms = []
        for value in sub["함정"].dropna():
            boundary_terms.extend(part.strip() for part in str(value).split(",") if part.strip())
        boundary_terms = sorted(set(boundary_terms))

        query_items = [
            {"type": str(row["유형"]).strip(), "text": str(row["질의"]).strip()}
            for _, row in sub.iterrows()
        ]

        out_families.append(
            {
                "family": fam,
                "split": final_split[fam],
                "intent_definition": build_intent_definition(fam, category),
                "positive_terms": positive_terms,
                "boundary_terms": boundary_terms,
                "queries": query_items,
            }
        )

    output_doc = {
        "query_set_version": NEW_QUERY_SET_VERSION,
        "families": out_families,
    }

    total_queries = sum(len(f["queries"]) for f in out_families)
    print(f"\n[요약] family {len(out_families)}개, 질의 {total_queries}개")

    if args.dry_run:
        print("\n[dry-run] 파일을 쓰지 않았습니다.")
        return

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_doc, f, allow_unicode=True, sort_keys=False, width=100)

    print(f"\n[완료] {args.output} 에 family {len(out_families)}개, 질의 {total_queries}개 작성")
    print("[주의] intent_definition은 자동 생성된 초안입니다 — 팀 검토 후 다듬어야 합니다.")
    print("[주의] RECLASSIFY_QUERIES의 재배정 근거(특히 '복합' family 2건)는 팀이 한 번 검토하세요.")


if __name__ == "__main__":
    main()
