"""`colab/*.py`(원본) → `colab/*.ipynb`(Colab에서 여는 파일) 변환.

원본을 .py로 두는 이유: git diff·코드 리뷰·ruff가 .py에서만 제대로 된다. Colab에서는 .py를 그대로 열 수 없어서
이 변환으로 노트북을 만든다(`scripts/build_colab_notebooks.py`). 둘이 어긋나면 tests/test_colab_notebooks.py가
실패한다 — .py를 고쳤으면 변환을 다시 돌려 .ipynb도 같이 커밋할 것.

셀 나누는 규칙:
- 맨 위 모듈 docstring → 첫 markdown 셀(제목 + 설명)
- 최상위의 `\"\"\"## 제목 ...\"\"\"` 문자열 → markdown 셀
- 그 사이 코드 → 코드 셀. 코드 안의 `# %%` 줄에서 셀을 더 나눈다(설치 / Drive 연결 / 설정 / 실행 등).
- `get_ipython().system("...")` → `!...`, `get_ipython().run_line_magic("a", "b")` → `%a b` (노트북 문법)
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

CELL_MARKER = "# %%"

NOTEBOOK_METADATA = {
    "accelerator": "GPU",
    "colab": {"gpuType": "T4", "provenance": []},
    "kernelspec": {"display_name": "Python 3", "name": "python3"},
    "language_info": {"name": "python"},
}


def _is_markdown_node(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _magic_replacement(node: ast.stmt) -> str | None:
    """`get_ipython().system(...)` / `.run_line_magic(...)` 문장을 노트북 매직 한 줄로 바꾼다(아니면 None)."""

    if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)):
        return None
    call = node.value
    func = call.func
    if not (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Call)
        and isinstance(func.value.func, ast.Name)
        and func.value.func.id == "get_ipython"
    ):
        return None
    args = [a.value for a in call.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    if len(args) != len(call.args):
        return None
    if func.attr == "system" and len(args) == 1:
        return "!" + args[0]
    if func.attr == "run_line_magic" and len(args) == 2:
        return f"%{args[0]} {args[1]}".rstrip()
    return None


def _code_cells(lines: list[str]) -> list[str]:
    """코드 줄들을 `# %%`에서 나누고, 앞뒤 빈 줄을 정리한 셀 소스 목록."""

    cells, current = [], []
    for line in lines:
        if line.strip() == CELL_MARKER:
            cells.append(current)
            current = []
        else:
            current.append(line)
    cells.append(current)
    result = []
    for cell in cells:
        text = "\n".join(cell).strip("\n")
        if text.strip():
            result.append(text)
    return result


def _markdown_from_docstring(text: str, title: str | None = None) -> str:
    body = text.strip("\n")
    if title is not None:
        # 모듈 docstring 첫 줄(예전 Colab 내보내기 파일명 "xxx.ipynb")은 제목으로 바꾼다
        first, _, rest = body.partition("\n")
        if first.strip().endswith(".ipynb"):
            body = rest.lstrip("\n")
        body = f"# {title}\n\n{body}"
    return body


def py_to_notebook(source: str, title: str, source_name: str) -> dict:
    """`.py` 소스 문자열을 nbformat 4 노트북 dict로 바꾼다."""

    lines = source.split("\n")
    if lines and lines[0].startswith("# -*- coding"):
        lines[0] = ""
    tree = ast.parse("\n".join(lines))

    # 매직으로 바꿀 문장은 줄 범위를 한 줄짜리로 치환(뒤에서부터 바꿔서 앞쪽 줄 번호가 안 밀리게)
    for node in sorted(tree.body, key=lambda n: n.lineno, reverse=True):
        replacement = _magic_replacement(node)
        if replacement is not None:
            lines[node.lineno - 1 : node.end_lineno] = [replacement]
    tree = ast.parse("\n".join(line if not line.startswith(("!", "%")) else "pass" for line in lines))

    cells: list[dict] = [
        _cell(
            "markdown",
            f"> 이 노트북은 `colab/{source_name}`에서 자동 생성됩니다(`python scripts/build_colab_notebooks.py`). "
            "코드를 고칠 때는 .py를 고치고 다시 생성하세요. 위에서부터 순서대로 실행하면 됩니다.",
        )
    ]
    cursor = 0  # 다음 코드가 시작할 줄 인덱스(0-based)
    for index, node in enumerate(tree.body):
        if not _is_markdown_node(node):
            continue
        cells += [_cell("code", c) for c in _code_cells(lines[cursor : node.lineno - 1])]
        docstring_title = title if index == 0 else None
        cells.append(_cell("markdown", _markdown_from_docstring(node.value.value, docstring_title)))
        cursor = node.end_lineno
    cells += [_cell("code", c) for c in _code_cells(lines[cursor:])]

    return {"cells": cells, "metadata": NOTEBOOK_METADATA, "nbformat": 4, "nbformat_minor": 0}


def _cell(kind: str, text: str) -> dict:
    source = text.split("\n")
    source = [line + "\n" for line in source[:-1]] + [source[-1]]
    cell = {"cell_type": kind, "metadata": {}, "source": source}
    if kind == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


def notebook_json(notebook: dict) -> str:
    return json.dumps(notebook, ensure_ascii=False, indent=1) + "\n"


def build_notebook_text(py_path: Path, title: str) -> str:
    return notebook_json(py_to_notebook(py_path.read_text(encoding="utf-8"), title, py_path.name))
