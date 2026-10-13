import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from pack_for_colab import _remove_previous_pack


def test_refuses_to_delete_working_dir_or_foreign_folder(tmp_path, monkeypatch):
    work = tmp_path / "repo"
    (work / "data").mkdir(parents=True)
    (work / "data" / "notes.csv").write_text("x", encoding="utf-8")
    monkeypatch.chdir(work)

    for output in (Path("."), tmp_path, Path("data")):   # 작업 폴더·상위 폴더·이 스크립트가 만들지 않은 폴더
        with pytest.raises(SystemExit):
            _remove_previous_pack(output)
    assert (work / "data" / "notes.csv").exists()

    packed = work / "colab_upload"
    (packed / "data").mkdir(parents=True)
    (packed / "data" / "data_version.json").write_text("{}", encoding="utf-8")
    _remove_previous_pack(packed)
    assert not packed.exists()
    _remove_previous_pack(packed)   # 없으면 아무것도 안 함
