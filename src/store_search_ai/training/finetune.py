"""fine-tuning에서 torch 없이 돌아가는 부분: 학습 행 펼치기, run 이름 규칙, 오래된 run 정리.

실제 학습(torch/sentence-transformers)은 `store_search_ai.training.st_finetune`에 있다. 여기 있는
함수들은 GPU 없는 로컬에서도 테스트할 수 있도록(tests/test_training_finetune.py) 일부러 분리했다.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

KEEP_MARKER = "KEEP"
"""run 폴더 안에 이 이름의 파일이 있으면 `prune_finetune_runs()`가 절대 지우지 않는다
(서비스 후보로 고른 체크포인트를 보호하는 용도 — Drive에서 빈 파일 하나만 만들면 된다)."""

PARTIAL_SUFFIX = ".partial"
"""Drive에 저장하는 도중인 폴더 이름 뒤에 붙는다. 저장+검증+manifest 기록이 전부 끝나야
최종 이름으로 바뀌므로, 이 접미사가 남아 있는 폴더는 중간에 끊긴 불완전한 결과다."""

CHECKPOINT_SUFFIX = ".ckpt"
"""학습 도중 한 번 저장하는 중간 체크포인트 폴더(`<TAG>.ckpt/checkpoint-N/`). Colab 연결이 끊겼을 때
이어서 학습하기 위한 것이라, 최종 모델 저장이 성공하면 지운다."""

RESUME_IGNORED_KEYS = frozenset({"resume_tag", "note", "extra", "keep_last_runs", "save_mid_checkpoint"})
"""이어서 학습할 때 처음 실행과 달라도 되는 설정 — 나머지가 하나라도 다르면 다른 실험이 섞이므로 거부한다."""

_OWNER_PATTERN = re.compile(r"^[a-z][a-z0-9]{1,15}$")
_CHECKPOINT_PATTERN = re.compile(r"^checkpoint-(\d+)$")


def make_run_tag(base_name: str, owner: str, now: datetime | None = None) -> str:
    """`{베이스모델}_ft_{사람}_{YYYYMMDD_HHMM}`(UTC) 형식의 run 이름을 만든다.

    예전에는 `{베이스모델}_ft_v1`로 고정이라 공유 Drive에서 팀원끼리(또는 같은 사람이 다시
    돌릴 때) 서로의 결과를 조용히 덮어썼다. 사람 이름과 시각을 넣어 run마다 고유하게 만든다.
    """

    if not _OWNER_PATTERN.fullmatch(owner):
        raise ValueError(
            f"OWNER={owner!r}: 영문 소문자로 시작하는 영문 소문자/숫자 2~16자로 정하세요 (예: 'jisu')"
        )
    now = now or datetime.now(UTC)
    return f"{run_tag_prefix(base_name, owner)}{now:%Y%m%d_%H%M}"


def run_tag_prefix(base_name: str, owner: str) -> str:
    """`prune_finetune_runs()`가 "내 run"을 알아보는 접두어 — 다른 팀원의 run은 절대 건드리지 않는다."""

    return f"{base_name}_ft_{owner}_"


def validate_resume_tag(tag: str, base_name: str, owner: str) -> str:
    """이어서 학습할 TAG가 지금 설정(베이스 모델·사람)의 run인지 확인한다 — 남의 run이나 다른
    모델의 체크포인트에 이어 붙이는 실수를 막는다."""

    tag = tag.strip()
    prefix = run_tag_prefix(base_name, owner)
    if not tag.startswith(prefix):
        raise ValueError(f"RESUME_TAG={tag!r}는 {prefix}로 시작해야 합니다(MODEL_CONFIG/OWNER가 처음 실행과 같은지 확인).")
    return tag


def latest_checkpoint(checkpoint_root: str | Path) -> Path | None:
    """`checkpoint_root` 밑의 `checkpoint-N` 중 N이 가장 큰 폴더(없으면 None)."""

    checkpoint_root = Path(checkpoint_root)
    if not checkpoint_root.is_dir():
        return None
    found = [
        (int(match.group(1)), d)
        for d in checkpoint_root.iterdir()
        if d.is_dir() and (match := _CHECKPOINT_PATTERN.fullmatch(d.name))
    ]
    return max(found)[1] if found else None


def config_mismatches(saved: dict, current: dict, ignore: frozenset[str] = RESUME_IGNORED_KEYS) -> list[str]:
    """처음 실행 때 저장한 설정과 지금 설정에서 값이 다른 키 목록(`ignore`는 제외)."""

    keys = (set(saved) | set(current)) - ignore
    return sorted(key for key in keys if saved.get(key) != current.get(key))


def iter_package_files(package_dir: str | Path) -> list[Path]:
    """코드 사본·해시에 넣을 파일 목록(캐시 파일 제외, 정렬 — 순서가 같아야 해시가 같다)."""

    return sorted(
        path
        for path in Path(package_dir).rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def package_tree_sha256(package_dir: str | Path) -> str:
    """패키지 폴더 전체(파일 경로 + 내용)의 해시.

    `scripts/pack_for_colab.py`가 올릴 때 한 번, 학습할 때 한 번 계산해서 비교한다 — 다르면 Drive에 올린 뒤
    Colab 편집기에서 코드를 고쳐서 학습했다는 뜻이다(이때 정확한 코드 기록은 모델 폴더의 code_snapshot.zip).
    """

    package_dir = Path(package_dir)
    digest = hashlib.sha256()
    for path in iter_package_files(package_dir):
        digest.update(path.relative_to(package_dir).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def expand_training_rows(
    records: list[dict],
    num_hard_negatives: int,
    max_positives_per_query: int | None,
) -> tuple[list[dict], dict]:
    """`train_pairs.jsonl` 레코드(query 하나)를 (query, positive) 하나당 한 행으로 펼친다.

    반환 행은 `{"anchor", "positive", "negative_1", ..., "negative_k"}` — sentence-transformers
    Trainer가 컬럼 순서대로 (anchor, positive, hard negatives)로 읽는 형식이다. 모든 행의 컬럼
    수가 같아야 하므로(행마다 다르면 학습이 바로 에러난다), hard negative가 `num_hard_negatives`개보다
    적은 query는 통째로 제외하고 개수를 stats에 남긴다.

    `max_positives_per_query`는 positive가 수백 개인 넓은 query(예: "한식")가 학습 데이터를 독점하지
    않게 자르는 상한이다. positives는 이미 relevance 높은 순으로 정렬돼 있으므로(prepare 단계)
    앞에서부터 자르면 relevance=3이 먼저 남는다. 예전 스키마(`"positive"` 단일 문자열)도 읽는다.
    """

    rows = []
    n_skipped_few_negatives = 0
    n_queries_used = 0

    for record in records:
        positives = record.get("positives")
        if positives is None:
            positives = [record["positive"]]
        if max_positives_per_query is not None:
            positives = positives[:max_positives_per_query]

        negatives = record["negatives"][:num_hard_negatives]
        if len(negatives) < num_hard_negatives:
            n_skipped_few_negatives += 1
            continue

        n_queries_used += 1
        negative_columns = {f"negative_{i + 1}": text for i, text in enumerate(negatives)}
        for positive in positives:
            rows.append({"anchor": record["query"], "positive": positive, **negative_columns})

    stats = {
        "n_queries_in_file": len(records),
        "n_queries_used": n_queries_used,
        "n_skipped_few_negatives": n_skipped_few_negatives,
        "n_rows": len(rows),
    }
    return rows, stats


def _created_at(run_dir: Path) -> str:
    manifest = json.loads((run_dir / "model_manifest.json").read_text(encoding="utf-8"))
    return manifest.get("created_at", "")


def prune_finetune_runs(
    run_root: str | Path, prefix: str, keep_last: int, dry_run: bool = False
) -> list[Path]:
    """`run_root` 밑에서 `prefix`로 시작하는 완성된 run 중 최신 `keep_last`개만 남기고 지운다.

    - `prefix`(= `run_tag_prefix(베이스모델, 사람)`)가 다른 폴더, 즉 다른 팀원이나 다른 베이스
      모델의 run은 대상이 아니다.
    - `KEEP` 파일이 있는 run은 지우지 않고, `keep_last` 개수에도 세지 않는다.
    - `model_manifest.json`이 없는 폴더와 `.partial` 폴더(저장 도중 끊긴 것)는 이 함수가 만든
      완성된 run인지 확신할 수 없으므로 건드리지 않는다.

    지운(또는 dry_run이면 지울) 폴더 목록을 오래된 순서로 반환한다.
    """

    if keep_last < 1:
        raise ValueError("keep_last는 1 이상이어야 합니다 (방금 만든 run까지 지우게 됨)")

    run_root = Path(run_root)
    candidates = [
        d
        for d in run_root.iterdir()
        if d.is_dir()
        and d.name.startswith(prefix)
        and not d.name.endswith(PARTIAL_SUFFIX)
        and (d / "model_manifest.json").exists()
        and not (d / KEEP_MARKER).exists()
    ]
    candidates.sort(key=lambda d: (_created_at(d), d.name), reverse=True)
    to_delete = sorted(candidates[keep_last:], key=lambda d: (_created_at(d), d.name))

    if not dry_run:
        for run_dir in to_delete:
            shutil.rmtree(run_dir)
    return to_delete
