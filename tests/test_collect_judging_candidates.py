import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from collect_judging_candidates import collect_candidates


def _write_run(path, rows):
    pd.DataFrame([{"query_id": q, "doc_id": d, "rank": r, "score": 1.0 / r, "system": "orig"} for q, d, r in rows]).to_csv(
        path, index=False, encoding="utf-8-sig")


def test_collect_candidates_merges_splits_renames_system_and_checks_depth(tmp_path):
    active = pd.DataFrame({"query_id": ["v1", "t1"], "split": ["val", "test"]})
    val, test = tmp_path / "val.csv", tmp_path / "test.csv"
    _write_run(val, [("v1", "a", 1), ("v1", "b", 2), ("v_inactive", "z", 1)])
    _write_run(test, [("t1", "c", 1), ("t1", "d", 2)])
    registry = {"round": "r", "depth": 2, "splits": ["val", "test"],
                "candidates": [{"name": "hyb", "val": str(val), "test": str(test)}]}
    out = tmp_path / "out"
    assert collect_candidates(registry, active, out) == {"hyb": 4}
    merged = pd.read_csv(out / "hyb.csv", encoding="utf-8-sig")
    assert set(merged["system"]) == {"hyb"} and set(merged["query_id"]) == {"v1", "t1"}   # 비활성 쿼리 제외

    registry["depth"] = 3                                   # 상위 3개가 안 되는 쿼리 → 멈춤
    with pytest.raises(SystemExit, match="상위 3개"):
        collect_candidates(registry, active, out)
    registry["depth"] = 2
    registry["candidates"].append({"name": "hyb", "val": str(val), "test": str(test)})
    with pytest.raises(SystemExit, match="중복"):
        collect_candidates(registry, active, out)
    with pytest.raises(SystemExit, match="test run 경로"):
        collect_candidates({**registry, "candidates": [{"name": "x", "val": str(val)}]}, active, out)
