import importlib
import sys

from store_search_ai.common.dev_reload import reload_project


def test_reload_project_picks_up_edited_source(tmp_path, monkeypatch):
    pkg = tmp_path / "demo_pkg_reload"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # 같은 초에 다시 써도 .pyc 캐시에 막히지 않게

    assert importlib.import_module("demo_pkg_reload.mod").VALUE == 1
    (pkg / "mod.py").write_text("VALUE = 2\n", encoding="utf-8")

    removed = reload_project("demo_pkg_reload")
    assert set(removed) == {"demo_pkg_reload", "demo_pkg_reload.mod"}
    assert importlib.import_module("demo_pkg_reload.mod").VALUE == 2
    reload_project("demo_pkg_reload")


def test_reload_project_leaves_other_packages_alone():
    sys.modules["store_search_ai_other_pkg"] = object()
    try:
        removed = reload_project("store_search_ai_x")
        assert removed == []
        assert "store_search_ai_other_pkg" in sys.modules
    finally:
        del sys.modules["store_search_ai_other_pkg"]
