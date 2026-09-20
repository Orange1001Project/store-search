"""리팩터링 전후로 11_build_qrels.py의 산출물이 동일한지 확인하는 golden-file 회귀 테스트.

benchmark/storesearch_ko_v1/qrels_*.csv/.trec, benchmark_manifest.json은 리팩터링 전
스크립트가 실제 adjudication 완료본 + provisional train qrels로 만든 진짜 결과물이다.
이 테스트는 리팩터링된 assemble_qrels()/build_manifest()를 같은 입력으로 실행해서 그
산출물과 완전히 동일한 파일이 나오는지 검증한다 — 출력은 실제 benchmark_dir이 아니라
tmp_path에 써서 체크인된 파일을 건드리지 않는다.
"""

from pathlib import Path

import pandas as pd
import pytest

from store_search_ai.data.qrels_builder import (
    assemble_qrels,
    build_manifest,
    build_split_qrels,
    load_adjudication,
    load_train_qrels,
    save_qrels_outputs,
)
from store_search_ai.pipeline.common import load_config, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_DIR = REPO_ROOT / "benchmark" / "storesearch_ko_v1"
ADJUDICATION_PATH = (
    BENCHMARK_DIR / "annotations" / "full_annotation_v1" / "analysis"
    / "adjudication_val_test_full_completed.csv"
)
TRAIN_QRELS_PATH = BENCHMARK_DIR / "qrels" / "provisional_v1" / "qrels_train_provisional.csv"
GOLDEN_MANIFEST_PATH = BENCHMARK_DIR / "benchmark_manifest.json"

pytestmark = pytest.mark.skipif(
    not ADJUDICATION_PATH.exists() or not TRAIN_QRELS_PATH.exists(),
    reason="adjudication/provisional train qrels 없음 (팀 공유 폴더에는 포함되어 있어야 함)",
)


def test_qrels_and_manifest_match_checked_in_golden_files(tmp_path):
    import json

    config = load_config(REPO_ROOT / "configs" / "benchmark" / "storesearch_ko_v1.yaml")

    queries_path = BENCHMARK_DIR / "queries.csv"
    queries = pd.read_csv(queries_path, encoding="utf-8-sig")
    active_queries = queries[queries["status"].astype(str).str.lower().eq("active")].copy()
    active_query_ids = set(active_queries["query_id"].astype(str))

    adj = load_adjudication(ADJUDICATION_PATH)
    qrels_val = build_split_qrels(adj, "val")
    qrels_test = build_split_qrels(adj, "test")
    qrels_train = load_train_qrels(TRAIN_QRELS_PATH)

    qrels_frames = assemble_qrels(qrels_train, qrels_val, qrels_test, active_query_ids)

    # 산출물은 tmp_path에 쓴다 — 체크인된 benchmark/ 파일을 건드리지 않기 위함.
    csv_paths, trec_paths = save_qrels_outputs(tmp_path, qrels_frames)

    manifest = build_manifest(
        config=config,
        active_query_count=int(active_queries["query_id"].nunique()),
        qrels_frames=qrels_frames,
        queries_path=queries_path,
        csv_paths=csv_paths,
        trec_paths=trec_paths,
        adjudication_path=ADJUDICATION_PATH,
        train_path=TRAIN_QRELS_PATH,
        sha256_file=sha256_file,
    )

    golden = json.loads(GOLDEN_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["splits"] == golden["splits"]
    assert manifest["query_count"] == golden["query_count"]
    # sha256 비교이므로, 이게 일치하면 qrels_*.csv/.trec 바이트 내용이 golden과 완전히 동일하다는 뜻이다.
    assert manifest["files"] == golden["files"]
