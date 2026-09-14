"""scripts/*.py 전반에서 반복되던 보일러플레이트를 모은 공통 유틸.

각 함수는 기존 스크립트들에 있던 코드를 그대로 옮긴 것이며 동작을 바꾸지 않았다
(리팩터링 전후로 산출물이 바이트 단위로 동일한지 재실행해서 확인함 —
docs/PIPELINE.md 및 각 스크립트 상단 주석 참고).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


def load_config(path: str | Path) -> dict:
    """벤치마크/데이터 설정 yaml을 로드한다.

    05, 06, 07, 08, 09, 10, 11, 12, 14, 15 스크립트에서 각자 구현하던
    `yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))` 패턴을 통합.
    """

    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def get_benchmark_dir(config: dict, create: bool = True) -> Path:
    """config["benchmark_dir"]를 Path로 반환하고, 필요하면 생성한다."""

    benchmark_dir = Path(config["benchmark_dir"])
    if create:
        benchmark_dir.mkdir(parents=True, exist_ok=True)
    return benchmark_dir


def sha256_file(path: str | Path) -> str:
    """파일 전체를 청크 단위로 읽어 SHA256 hexdigest를 반환한다.

    05_init_benchmark.py, 11_build_qrels.py에 각각 있던 동일 구현을 통합.
    (config/queries 변경 추적용 — data/corpus의 text_hash와는 별개 용도)
    """

    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_active_queries(benchmark_dir: str | Path) -> pd.DataFrame:
    """benchmark_dir/queries.csv를 읽어 status == "active" 인 행만 반환한다.

    05(생성 직후 제외)를 뺀 06, 07, 12, 14에서 반복되던
    `queries = pd.read_csv(...); queries = queries[queries["status"] == "active"]`
    패턴을 통합.
    """

    queries = pd.read_csv(Path(benchmark_dir) / "queries.csv", encoding="utf-8-sig")
    return queries[queries["status"].astype(str).str.lower() == "active"].copy()


def write_trec_qrels(frame: pd.DataFrame, path: str | Path) -> None:
    """query_id/doc_id/relevance 컬럼을 가진 DataFrame을 TREC qrels 포맷으로 저장한다.

    포맷: "{query_id} 0 {doc_id} {relevance}"
    09_prepare_full_annotations.py, 11_build_qrels.py에 각각 있던 동일 구현을 통합.
    """

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in frame.itertuples(index=False):
            f.write(f"{row.query_id} 0 {row.doc_id} {int(row.relevance)}\n")


def write_model_manifest(model_dir: str | Path, manifest: dict) -> Path:
    """fine-tuning 직후 `model_dir/model_manifest.json`에 체크포인트 메타데이터를 기록한다.

    가중치 파일만 있으면 나중에(서비스에 실제로 가져다 쓸 때) "이 체크포인트가 정확히
    어떤 base 모델을, 어떤 데이터/버전으로, 어떤 하이퍼파라미터로 학습한 것인지" 알 방법이
    없어진다 — 이 매니페스트가 그 기록이다. `evaluations`는 빈 리스트로 시작하고,
    `14_run_model_eval.py`가 이 모델을 평가할 때마다 `append_model_manifest_evaluation()`으로
    채워진다(학습 시점엔 아직 val/test 점수를 모르므로).
    `colab/run_finetune_qwen3.py`, `colab/run_finetune_simple.py`에서 호출한다.
    """

    manifest = {
        **manifest,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "evaluations": manifest.get("evaluations", []),
    }
    path = Path(model_dir) / "model_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def append_model_manifest_evaluation(model_dir: str | Path, entry: dict) -> None:
    """model_dir/model_manifest.json이 있으면 evaluations 리스트에 이번 평가 결과를 추가한다.

    manifest가 없으면 조용히 건너뛴다 — HF Hub에서 바로 받는 zero-shot 모델(로컬 디렉터리가
    아님)은 애초에 이 매니페스트의 대상이 아니기 때문. `14_run_model_eval.py`가 평가 직후 호출한다.
    """

    path = Path(model_dir) / "model_manifest.json"
    if not path.exists():
        return

    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest.setdefault("evaluations", []).append(entry)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
