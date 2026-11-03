"""서비스셋 쿼리 전체를 한 표로 내보낸다 — <benchmark_dir>/queries.csv (2026-10-27부터 최신 전체 표).

가져온 쿼리 표(data/query/service_queries_v1.csv)에 다음 열을 붙인다. 회의·검토용 설명 열이고, 판정·채점 규칙은 바꾸지 않는다.
  - batch     처음 들어온 묶음(instances.csv random 사례의 batch): v1(1차 500개) / extra(추가 C) / extra_b(추가 B) / extra_a(A head)
  - source    누가 썼나: 작성자(W1~W3) / 팀(B) / 진행자(E) / 기존 벤치마크(A head)
  - freq      A만: head(기존 벤치마크 업종) / tail(새 업종)
  - eval_set  주 평가셋에 든 split(dev/test, 없으면 빈칸)과 쓴 사례(random/anchor)
  - n_judged, n_relevant  판정한 가맹점 수와 그중 정답(2점 이상) 수(위치 무관, 전국)

이전에는 이 파일이 1차 판정(service_v1) 쿼리 498개만 담았다. pool의 main 묶음은 이제 batch == v1로 고른다(build_service_pool.py).

사용법:
    python scripts/export_service_query_table.py
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from store_search_ai.pipeline.common import load_config

logger = logging.getLogger(__name__)


def source_of(writers: str) -> str:
    if "old_benchmark" in writers:
        return "기존 벤치마크"
    if writers.startswith("team"):
        return "팀"
    if writers == "facilitator":
        return "진행자"
    return "작성자"


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config("configs/query/service_queryset_v1.yaml")
    bdir = Path(cfg["judging"]["benchmark_dir"])
    q = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    batch = inst[inst["context"] == "random"].drop_duplicates("query_id").set_index("query_id")["batch"]
    ev = pd.read_csv(bdir / "eval_set.csv", encoding="utf-8-sig").set_index("query_id")
    qrels = pd.read_csv(bdir / "qrels.csv", encoding="utf-8-sig")
    judged = qrels.groupby("query_id").agg(n_judged=("doc_id", "size"), n_relevant=("relevance", lambda s: int((s >= 2).sum())))

    out = q.assign(batch=q["query_id"].map(batch).fillna(""), source=q["writers"].map(source_of))
    out["freq"] = [("head" if s == "기존 벤치마크" else "tail") if b == "A" else ""
                   for b, s in zip(out["bundle"], out["source"], strict=True)]
    out["eval_set"] = out["query_id"].map(lambda i: f"{ev.at[i, 'split']}/{ev.at[i, 'context']}" if i in ev.index else "")
    out = out.join(judged, on="query_id")
    out[["n_judged", "n_relevant"]] = out[["n_judged", "n_relevant"]].fillna(0).astype(int)
    path = bdir / "queries.csv"
    out.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    act = out[out["status"] == "active"]
    logger.info("쿼리 %d개(활성 %d) → %s", len(out), len(act), path)
    logger.info("묶음 × batch(활성):\n%s", pd.crosstab(act["bundle"], act["batch"]).to_string())


if __name__ == "__main__":
    main()
