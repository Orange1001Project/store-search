"""Colab(Drive)에 올릴 **데이터 폴더**를 만든다 — 처음 한 번, 그리고 데이터가 바뀔 때만.

학습·평가 코드는 `colab/train_eval.ipynb` 노트북 안에 전부 들어 있어서 Drive에 코드를 올릴 필요가 없다. 이 스크립트는
노트북이 읽는 데이터만 `colab_upload/data/`에 모으고, 각 파일의 sha256·git 커밋·채점 설정을 `data_version.json`에 적는다
(노트북이 이 파일을 읽어 학습 기록(manifest)과 채점 설정에 그대로 쓴다).

들어가는 것: train_pairs.jsonl, train_pairs.meta.json, corpus parquet, queries.csv, qrels_val.trec, qrels_test.trec,
data_version.json.

사용법:
    python scripts/pack_for_colab.py
    → colab_upload/data/ 를 Drive `내 드라이브/store-search-ai/data/` 로 업로드(기존 data 폴더는 지우고)
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from store_search_ai.pipeline.common import load_config, sha256_file


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, check=True, encoding="utf-8").stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--output", default="colab_upload")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    corpus_path = Path(config["corpus_path"])
    sources = [
        Path("data/finetune/train_pairs.jsonl"),
        Path("data/finetune/train_pairs.meta.json"),
        corpus_path,
        benchmark_dir / "queries.csv",
        benchmark_dir / "qrels_val.trec",
        benchmark_dir / "qrels_test.trec",
    ]
    missing = [str(p) for p in sources if not p.exists()]
    if missing:
        raise SystemExit(f"없는 파일: {missing} — 학습 데이터는 prepare_finetune_dataset.py, 정답은 11_build_qrels.py로 만든다")

    data_dir = Path(args.output) / "data"
    if Path(args.output).exists():
        shutil.rmtree(args.output)  # 예전 project/ 형식 결과물도 같이 지운다
    data_dir.mkdir(parents=True)
    for source in sources:
        shutil.copy2(source, data_dir / source.name)

    evaluation = config.get("evaluation", {})
    data_version = {
        "packed_at": datetime.now(UTC).isoformat(),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_commit": _git("rev-parse", "HEAD"),
        "benchmark_version": config["benchmark_version"],
        "corpus_version": config["corpus_version"],
        "corpus_file": corpus_path.name,
        "evaluation": {
            "bootstrap_samples": int(evaluation.get("bootstrap_samples", 10000)),
            "random_seed": int(evaluation.get("random_seed", 20260831)),
            "binary_relevance_threshold": int(evaluation.get("binary_relevance_threshold", 2)),
        },
        "files": {source.name: sha256_file(source) for source in sources},
    }
    (data_dir / "data_version.json").write_text(
        json.dumps(data_version, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    print(f"[완료] {data_dir}  (커밋 {str(data_version['git_commit'])[:7]})")
    for name, digest in data_version["files"].items():
        print(f"  - {name}  sha256 {digest[:12]}")
    print("다음: Drive '내 드라이브/store-search-ai/'의 기존 data 폴더를 지우고 이 data 폴더를 올리세요.")
    print("      코드는 colab/train_eval.ipynb 노트북 하나만 Colab에서 열면 됩니다(코드 업로드 불필요).")


if __name__ == "__main__":
    main()
