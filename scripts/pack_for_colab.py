"""Colab(Drive)에 올릴 `project/` 폴더를 만든다 — 지금 로컬 코드 그대로 + 코드 버전 기록.

손으로 Drive에 src/, configs/ 등을 골라 올리다 보면 빠뜨리거나 예전 파일이 섞인다. 이 스크립트가 필요한
것만 한 폴더에 모으고, `project/code_version.json`에 git 커밋/브랜치/커밋 안 된 수정 파일 목록을 자동으로
적는다. Colab 학습(`store_search_ai.training.st_finetune`)이 이 파일을 읽어 model_manifest.json의
`code.version`에 그대로 남기므로, 사람이 커밋 번호를 따로 적을 필요가 없다
(학습에 쓴 코드 사본 자체도 모델 폴더의 `code_snapshot.zip`에 저장된다).

파이프라인 번호가 없는 이유: 01~15 실행 순서와 무관하게, Colab에 코드를 올릴 때마다 실행하는 도구다.

사용법:
    python scripts/pack_for_colab.py                  # 학습 + Colab 안에서 평가(채점)까지 할 수 있는 전부
    python scripts/pack_for_colab.py --no-eval-data   # 코드·학습 데이터만(평가 안 할 때, 업로드 용량 ↓)

기본으로 들어가는 것: src/store_search_ai, configs/models, configs/benchmark(채점 설정), 학습 데이터,
corpus parquet, queries.csv, qrels_val.trec, qrels_test.trec(최종 test 평가용 — 노트북에서 기본으로 막혀 있음).

결과: `colab_upload/project/` → Drive `내 드라이브/store-search-ai/`에 있던 `project` 폴더를 지우고 이 폴더를 올린다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from store_search_ai.pipeline.common import load_config
from store_search_ai.training.finetune import package_tree_sha256


def _git(*args: str, strip: bool = True) -> str | None:
    try:
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=True, encoding="utf-8")
    except (OSError, subprocess.CalledProcessError):
        return None
    # porcelain 출력은 줄 앞 공백이 상태 코드의 일부라서 strip하면 첫 파일 경로가 잘린다
    return result.stdout.strip() if strip else result.stdout


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--output", default="colab_upload")
    parser.add_argument(
        "--no-eval-data", action="store_true", help="corpus·queries·qrels를 빼고 코드·학습 데이터만 올린다"
    )
    parser.add_argument("--with-eval-data", action="store_true", help=argparse.SUPPRESS)  # 예전 옵션(이제 기본값)
    args = parser.parse_args()

    config = load_config(args.config)
    project_dir = Path(args.output) / "project"
    if project_dir.exists():
        shutil.rmtree(project_dir)

    items = [Path("src/store_search_ai"), Path("configs/models"), Path(args.config)]
    for name in ("train_pairs.jsonl", "train_pairs.meta.json"):
        path = Path("data/finetune") / name
        if path.exists():
            items.append(path)
        else:
            print(f"[안내] {path} 없음 — 학습 데이터 없이 코드만 올립니다(smoke test는 가능)")
    if not args.no_eval_data:
        benchmark_dir = Path(config["benchmark_dir"])
        items += [Path(config["corpus_path"]), benchmark_dir / "queries.csv"]
        for split in ("val", "test"):
            qrels = benchmark_dir / f"qrels_{split}.trec"
            if qrels.exists():
                items.append(qrels)
            else:
                print(f"[안내] {qrels} 없음 — Colab에서 {split} 채점은 못 합니다(11_build_qrels.py 이후 다시 pack)")

    for item in items:
        _copy(item, project_dir / item)

    changed = _git("status", "--porcelain", "--", "src", "configs", strip=False) or ""
    changed_files = [line[3:] for line in changed.splitlines() if line.strip()]
    code_version = {
        "packed_at": datetime.now(UTC).isoformat(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "HEAD"),
        "uncommitted_changes": bool(changed_files),
        "uncommitted_files": changed_files,
        # 학습 때 다시 계산해서 비교 — 다르면 Colab 편집기에서 고친 코드로 학습했다는 뜻
        "src_tree_sha256": package_tree_sha256(project_dir / "src" / "store_search_ai"),
    }
    (project_dir / "code_version.json").write_text(
        json.dumps(code_version, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    print(f"[완료] {project_dir}  (브랜치 {code_version['git_branch']}, 커밋 {str(code_version['git_commit'])[:7]})")
    for item in items:
        print(f"  - {item.as_posix()}")
    if changed_files:
        print(
            f"[안내] 커밋 안 된 수정 {len(changed_files)}개가 그대로 들어갑니다: {changed_files[:5]} — 괜찮습니다"
            "(학습 코드 사본이 모델 폴더에 저장됨). 좋은 결과가 나오면 그때 커밋하세요."
        )
    print("다음: Drive '내 드라이브/store-search-ai/'의 기존 project 폴더를 지우고 이 project 폴더를 올리세요.")


if __name__ == "__main__":
    main()
