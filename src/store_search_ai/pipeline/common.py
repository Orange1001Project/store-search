"""scripts/*.py 전반에서 반복되던 보일러플레이트를 모은 공통 유틸.

각 함수는 기존 스크립트들에 있던 코드를 그대로 옮긴 것이며 동작을 바꾸지 않았다
(리팩터링 전후로 산출물이 바이트 단위로 동일한지 재실행해서 확인함 —
docs/PIPELINE.md 및 각 스크립트 상단 주석 참고).
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

DEFAULT_ANNOTATION_ROUND = "full_annotation_v1"
"""08~11번 스크립트(애노테이션 시트~최종 qrels 직전의 provisional qrels)가 공유하는 기본
라운드 이름. 예전에는 이 문자열이 각 스크립트에 따로 하드코딩돼 있어서 새 라운드를 시작해도
전부 같은 디렉터리(annotations/full_annotation_v1/, qrels/provisional_v1/)에 덮어써졌다 —
`--round`로 라운드마다 별도 디렉터리를 쓰게 바꾼 뒤에도 기본값 하나는 여기서만 관리한다."""


def get_annotation_round_dirs(benchmark_dir: str | Path, round_name: str) -> tuple[Path, Path]:
    """애노테이션 라운드 하나의 표준 디렉터리 레이아웃을 반환한다: (시트/조정 디렉터리,
    provisional qrels 디렉터리).

    08(시트 생성)부터 11(최종 qrels 조립)까지 전부 이 함수로만 라운드 경로를 얻는다 — 라운드
    이름이 다르면 완전히 다른 디렉터리에 쌓이므로, 새 라운드로 다시 돌려도 이전 라운드의
    시트/조정/판정 결과를 덮어쓰지 않는다(TREC 스타일 벤치마크에서 pooling/annotation
    라운드를 버전 디렉터리로 분리 보관하는 것과 같은 관례). 최종 qrels(11번 출력)는 라운드와
    무관하게 `benchmark_dir` 바로 밑에 만들어진다 — "지금 gold로 쓰는 유일한 버전"이라는
    의미이며, 과거 버전을 남기고 싶으면 `11_build_qrels.py --freeze`로 `frozen/`에 스냅샷을 뜬다.
    """

    benchmark_dir = Path(benchmark_dir)
    annotations_dir = benchmark_dir / "annotations" / round_name
    provisional_qrels_dir = benchmark_dir / "qrels" / round_name
    return annotations_dir, provisional_qrels_dir


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
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in frame.itertuples(index=False):
            f.write(f"{row.query_id} 0 {row.doc_id} {int(row.relevance)}\n")


def write_model_manifest(model_dir: str | Path, manifest: dict) -> Path:
    """fine-tuning 직후 `model_dir/model_manifest.json`에 체크포인트 메타데이터를 기록한다.

    가중치 파일만 있으면 나중에(서비스에 실제로 가져다 쓸 때) "이 체크포인트가 정확히
    어떤 base 모델을, 어떤 데이터/버전으로, 어떤 하이퍼파라미터로 학습한 것인지" 알 방법이
    없어진다 — 이 매니페스트가 그 기록이다. `evaluations`는 빈 리스트로 시작하고,
    `14_run_model_eval.py`가 이 모델을 평가할 때마다 `append_model_manifest_evaluation()`으로
    채워진다(학습 시점엔 아직 val/test 점수를 모르므로).
    `store_search_ai.training.st_finetune.run_finetune()`(= `colab/run_finetune_*.py`)이 호출한다.
    """

    manifest = {
        **manifest,
        "created_at": datetime.now(UTC).isoformat(),
        "evaluations": manifest.get("evaluations", []),
    }
    path = Path(model_dir) / "model_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
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
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
