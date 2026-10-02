"""colab/*.py(원본)로부터 Colab에서 여는 colab/*.ipynb를 생성한다.

변환 규칙은 src/store_search_ai/common/colab_notebook.py 참고. .py를 고친 뒤에는 이걸 다시 돌려
.ipynb도 같이 커밋한다(tests/test_colab_notebooks.py가 둘이 어긋나면 실패한다).

사용법:
    python scripts/build_colab_notebooks.py           # .ipynb 생성/갱신
    python scripts/build_colab_notebooks.py --check   # 갱신이 필요한지만 확인(필요하면 종료코드 1)
"""

from __future__ import annotations

import argparse
from pathlib import Path

from store_search_ai.common.colab_notebook import build_notebook_text

COLAB_DIR = Path(__file__).resolve().parents[1] / "colab"

NOTEBOOKS = {
    "run_model_eval_encoding.py": "모델 평가 인코딩 (zero-shot / fine-tuned 공통)",
    "smoke_test_finetune.py": "Fine-tuning smoke test (가짜 데이터)",
    "run_finetune_simple.py": "Fine-tuning — Snowflake Arctic / BGE-M3 (full)",
    "run_finetune_qwen3.py": "Fine-tuning — Qwen3-Embedding (LoRA)",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    stale = []
    for py_name, title in NOTEBOOKS.items():
        py_path = COLAB_DIR / py_name
        nb_path = py_path.with_suffix(".ipynb")
        text = build_notebook_text(py_path, title)
        current = nb_path.read_text(encoding="utf-8") if nb_path.exists() else None
        if current == text:
            print(f"[최신] {nb_path.name}")
            continue
        stale.append(nb_path.name)
        if not args.check:
            nb_path.write_text(text, encoding="utf-8", newline="\n")
            print(f"[생성] {nb_path.name}")

    if args.check and stale:
        raise SystemExit(f"갱신 필요: {stale} — python scripts/build_colab_notebooks.py 실행")


if __name__ == "__main__":
    main()
