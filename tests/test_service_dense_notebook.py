"""colab/service_dense_runs.ipynb의 반경 안 상위 결과 셀(`# @cell runs`)이 로컬 service_pool과 같은 결과를 내는지 확인한다."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.data.service_pool import candidates_within, distances_km, top_k_run

NOTEBOOK = Path(__file__).resolve().parents[1] / "colab" / "service_dense_runs.ipynb"


def _cell_namespace() -> dict:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    source = next("".join(c["source"]) for c in cells
                  if c["cell_type"] == "code" and "".join(c["source"]).startswith("# @cell runs"))
    ns: dict = {}
    exec(compile(source, "<notebook:runs>", "exec"), ns)  # noqa: S102
    return ns


def test_notebook_radius_runs_match_local_rules():
    rng = np.random.default_rng(0)
    n = 300
    docs = pd.DataFrame({"doc_id": [f"d{i}" for i in range(n)], "latitude": 37.5 + rng.normal(0, 0.02, n),
                         "longitude": 127.0 + rng.normal(0, 0.02, n)})
    queries = pd.DataFrame({"query_id": ["q1", "q2", "q3"], "latitude": [37.5, 37.51, 37.5],
                            "longitude": [127.0, 127.01, 127.0]})
    doc_emb = rng.normal(size=(n, 8)).astype("float32")
    doc_emb[5] = doc_emb[7]                                   # 동점 처리도 같아야 함
    q_emb = rng.normal(size=(3, 8)).astype("float32")

    ns = _cell_namespace()
    got = ns["radius_runs"](docs, queries, doc_emb, q_emb, 1.0, 10, "m")

    cands = candidates_within(queries, docs, 1.0)
    want = pd.concat([top_k_run(qid, cands[qid], doc_emb[cands[qid]] @ q_emb[i], docs["doc_id"].to_numpy(), 10, "m")
                      for i, qid in enumerate(queries["query_id"])], ignore_index=True)
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True), check_dtype=False)


def test_notebook_radius_runs_keep_top_depth_per_radius_like_local():
    rng = np.random.default_rng(1)
    n = 400
    docs = pd.DataFrame({"doc_id": [f"d{i}" for i in range(n)], "latitude": 37.5 + rng.normal(0, 0.01, n),
                         "longitude": 127.0 + rng.normal(0, 0.01, n)})
    queries = pd.DataFrame({"query_id": ["q1", "q2"], "latitude": [37.5, 37.505], "longitude": [127.0, 127.004]})
    doc_emb = rng.normal(size=(n, 8)).astype("float32")
    q_emb = rng.normal(size=(2, 8)).astype("float32")

    got = _cell_namespace()["radius_runs"](docs, queries, doc_emb, q_emb, 2.0, 5, "m", [0.3, 2.0])

    cands = candidates_within(queries, docs, 2.0)
    dist = distances_km(queries, docs, cands)
    want = pd.concat([top_k_run(qid, cands[qid], doc_emb[cands[qid]] @ q_emb[i], docs["doc_id"].to_numpy(), 5, "m",
                                dist[qid], [0.3, 2.0]) for i, qid in enumerate(queries["query_id"])], ignore_index=True)
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True), check_dtype=False)
    near = set(docs["doc_id"][distances_km(queries.iloc[:1], docs, {"q1": np.arange(n)})["q1"] <= 0.3])
    q1 = got[got["query_id"] == "q1"]
    assert q1["doc_id"].isin(near).sum() == min(5, len(near))      # 작은 반경 상위 5개가 다 들어 있다
    assert (q1["rank"].head(5).to_numpy() == np.arange(1, 6)).all()


def test_every_code_cell_compiles():
    # Colab에서 처음 실행할 때 문법 오류로 멈추지 않게(2026-10-27: 문자열 안 줄바꿈으로 셀 하나가 깨졌던 일)
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    for i, c in enumerate(cells):
        if c["cell_type"] == "code":
            compile("".join(c["source"]), f"<notebook cell {i}>", "exec")
