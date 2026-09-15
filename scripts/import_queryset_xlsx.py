"""data/query/queryset_final.xlsx (팀 3안을 합친 최종 쿼리 시트)를
configs/benchmark/query_families_v1.yaml로 변환한다.

파이프라인 번호가 없는 이유: 05_init_benchmark.py *이전*에 한 번(또는 xlsx가 다시
바뀔 때마다) 사람이 검토 후 실행하는 저작 도구이며, 01~18 실행 순서에는 속하지
않는다. 실행 후에는 그대로 05_init_benchmark.py부터 다시 돌리면 된다.

변환 로직은 src/store_search_ai/data/query_import.py에 있다. 이 스크립트는 xlsx/yaml
IO와 인자 파싱만 담당한다. 재배정 규칙(무엇을 어떤 family로 정정하는지)과 seed는
코드에 하드코딩하지 않고 configs/benchmark/storesearch_ko_v1.yaml의 `query_set` 블록과
그것이 가리키는 configs/query/*.yaml에서 읽는다 — 자세한 내용/이유는
docs/EXTENDING_DATA.md 참고.

xlsx 시트 구성(팀이 만든 그대로):
  - 통합질의: 질의, 패밀리, 대분류, 유형(T1~T6), 태그, 출처, 합의, 원본유형,
    현행 결과, 관련 가맹점, 함정
  - 패밀리목록: 패밀리, 대분류, 우선순위(필수/권장/보류), ...

사용법:
    python scripts/import_queryset_xlsx.py
    python scripts/import_queryset_xlsx.py --input data/query/queryset_final.xlsx \
        --output configs/benchmark/query_families_v1.yaml --dry-run
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd
import yaml

from store_search_ai.data.query_import import build_query_families, parse_corrections
from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/query/queryset_final.xlsx")
    parser.add_argument("--output", default="configs/benchmark/query_families_v1.yaml")
    parser.add_argument(
        "--existing-families",
        default="configs/benchmark/query_families_v1.yaml",
        help="split 상속 기준이 될 현재 yaml (보통 --output과 동일 파일)",
    )
    parser.add_argument(
        "--config",
        default="configs/benchmark/storesearch_ko_v1.yaml",
        help="query_set.version/random_seed/corrections_path를 읽어올 벤치마크 설정",
    )
    parser.add_argument(
        "--corrections",
        default=None,
        help="RECLASSIFY_QUERIES/AMBIGUOUS_SLUGS가 담긴 yaml (기본: --config의 query_set.corrections_path)",
    )
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 요약만 출력")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config = load_config(args.config)
    query_set_config = config["query_set"]
    corrections_path = args.corrections or query_set_config["corrections_path"]

    with open(args.existing_families, encoding="utf-8") as f:
        existing = yaml.safe_load(f)
    existing_split_by_family = {fam["family"]: fam["split"] for fam in existing["families"]}

    corrections_raw = load_config(corrections_path)
    reclassify_queries, ambiguous_slugs = parse_corrections(corrections_raw)

    xls = pd.ExcelFile(args.input)
    queries = xls.parse("통합질의")
    fam_list = xls.parse("패밀리목록")

    output_doc = build_query_families(
        queries=queries,
        fam_list=fam_list,
        existing_split_by_family=existing_split_by_family,
        reclassify_queries=reclassify_queries,
        ambiguous_slugs=ambiguous_slugs,
        random_seed=query_set_config["random_seed"],
        query_set_version=query_set_config["version"],
    )

    if args.dry_run:
        logger.info("[dry-run] 파일을 쓰지 않았습니다.")
        return

    with open(args.output, "w", encoding="utf-8") as f:
        yaml.safe_dump(output_doc, f, allow_unicode=True, sort_keys=False, width=100)

    total_queries = sum(len(f["queries"]) for f in output_doc["families"])
    logger.info(
        "[완료] %s 에 family %d개, 질의 %d개 작성",
        args.output, len(output_doc["families"]), total_queries,
    )
    logger.info("[주의] intent_definition은 자동 생성된 초안입니다 — 팀 검토 후 다듬어야 합니다.")
    logger.info("[주의] 재배정 근거(특히 '복합' family 2건)는 팀이 %s에서 검토하세요.", corrections_path)


if __name__ == "__main__":
    main()
