import json
import sys
from pathlib import Path

import pytest

from store_search_ai.common.colab_notebook import build_notebook_text, py_to_notebook

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from build_colab_notebooks import COLAB_DIR, NOTEBOOKS


@pytest.mark.parametrize("py_name,title", NOTEBOOKS.items())
def test_checked_in_notebook_matches_py_source(py_name, title):
    py_path = COLAB_DIR / py_name
    nb_path = py_path.with_suffix(".ipynb")
    assert nb_path.exists(), f"{nb_path.name} 없음 — python scripts/build_colab_notebooks.py"
    assert nb_path.read_text(encoding="utf-8") == build_notebook_text(py_path, title), (
        f"{py_name}을 고친 뒤 노트북을 다시 생성하지 않았습니다 — python scripts/build_colab_notebooks.py"
    )


def test_py_to_notebook_splits_cells_and_converts_magics():
    source = '''# -*- coding: utf-8 -*-
"""old_name.ipynb

설명 한 줄
"""

import torch

# %%
get_ipython().system(
    'pip -q install "a==1" '
    '"b==2"'
)
get_ipython().run_line_magic("autoreload", "2")

"""## 설정"""

X = 1
'''
    nb = py_to_notebook(source, "제목", "x.py")
    cells = [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]
    assert cells[1] == ("markdown", "# 제목\n\n설명 한 줄")
    assert cells[2] == ("code", "import torch")
    assert cells[3] == ("code", '!pip -q install "a==1" "b==2"\n%autoreload 2')
    assert cells[4] == ("markdown", "## 설정")
    assert cells[5] == ("code", "X = 1")
    assert nb["metadata"]["accelerator"] == "GPU"
    json.dumps(nb)  # 직렬화 가능
