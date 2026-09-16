
from store_search_ai.models.leaderboard import build_leaderboard, find_runs


def test_find_runs_discovers_run_files_and_parses_template(tmp_path):
    (tmp_path / "model_a").mkdir()
    (tmp_path / "model_a" / "run_t1_minimal_val.csv").write_text("data", encoding="utf-8")
    (tmp_path / "model_a" / "run_t2_market_val.csv").write_text("data", encoding="utf-8")
    (tmp_path / "model_a" / "run_t1_minimal_test.csv").write_text("data", encoding="utf-8")
    (tmp_path / "not_a_dir.txt").write_text("data", encoding="utf-8")

    runs = list(find_runs(tmp_path, "val"))
    assert {(tag, template) for tag, template, _ in runs} == {
        ("model_a", "t1_minimal"), ("model_a", "t2_market"),
    }


def test_find_runs_sorts_tag_directories_and_run_files(tmp_path):
    for tag in ["zeta", "alpha"]:
        (tmp_path / tag).mkdir()
        (tmp_path / tag / "run_t1_minimal_val.csv").write_text("data", encoding="utf-8")
    runs = list(find_runs(tmp_path, "val"))
    assert [tag for tag, _, _ in runs] == ["alpha", "zeta"]


def test_build_leaderboard_sorts_by_ndcg_descending():
    rows = [
        {"tag": "a", "template": "t1", "nDCG@10": 0.3},
        {"tag": "b", "template": "t1", "nDCG@10": 0.8},
    ]
    leaderboard = build_leaderboard(rows)
    assert list(leaderboard["tag"]) == ["b", "a"]


def test_build_leaderboard_falls_back_to_last_column_when_no_ndcg():
    rows = [
        {"tag": "a", "template": "t1", "some_metric": 0.1},
        {"tag": "b", "template": "t1", "some_metric": 0.9},
    ]
    leaderboard = build_leaderboard(rows)
    assert list(leaderboard["tag"]) == ["b", "a"]
