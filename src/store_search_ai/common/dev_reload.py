"""Colab 편집기에서 Drive의 `src/` 코드를 고친 뒤, 세션을 다시 시작하지 않고 새 코드를 불러오기 위한 함수.

IPython의 `%load_ext autoreload`를 쓰지 않는 이유: Colab은 Python 3.13인데 IPython이 7.34로 고정돼 있고, 그 버전의
autoreload 확장은 Python 3.12에서 삭제된 `imp` 모듈을 import해서 `ModuleNotFoundError: No module named 'imp'`가 난다.
대신 이 함수가 `store_search_ai` 모듈들을 `sys.modules`에서 지워 두면, 다음 `from store_search_ai... import ...`가
Drive의 최신 파일을 다시 읽는다. 노트북의 설정 셀·평가 셀 맨 앞에서 호출한다.
"""

from __future__ import annotations

import importlib
import sys

PACKAGE = "store_search_ai"


def reload_project(package: str = PACKAGE) -> list[str]:
    """`package`와 그 하위 모듈을 전부 언로드한다(다음 import 때 디스크의 최신 코드로 다시 로드). 지운 모듈 이름을 반환."""

    names = [name for name in sys.modules if name == package or name.startswith(package + ".")]
    for name in names:
        del sys.modules[name]
    importlib.invalidate_caches()  # Drive에 새로 만든 파일도 찾게
    return names
