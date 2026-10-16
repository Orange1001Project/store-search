"""등록된 판정 후보(configs/benchmark/judging_candidates.yaml)를 모아 **한 번에** 보충 판정 시트를 만든다.

docs/EVALUATION_POLICY.md 3절의 일괄 판정 절차. 후보마다 val·test run을 하나로 합쳐(시스템 이름 = 후보 name)
results/judging_candidates/<round>/<name>.csv로 정리하고, 16_supplemental_round.py make-runs에 넘긴다.
pool에 이미 있는 (쿼리, 문서)는 다시 판정하지 않으므로, 이미 판정된 후보를 넣어도 비용이 늘지 않는다.

    python scripts/collect_judging_candidates.py            # 후보 검증 + depth별 판정 건수(시트는 안 만듦)
    python scripts/collect_judging_candidates.py --make --reason "최종 후보 일괄 판정"
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

from store_search_ai.pipeline.common import load_active_queries, load_config

RUN_COLUMNS = ["query_id", "doc_id", "rank", "score", "system"]
NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9_+.\-]*")
KEEP_DEPTH = 30   # make-runs --dry-run 표(10/20/30)를 그대로 쓰려고 상위 30개까지 남긴다


def collect_candidates(registry: dict, active: pd.DataFrame, out_dir: Path) -> dict[str, int]:
    """후보마다 split별 run을 검증·합쳐 out_dir/<name>.csv로 쓴다. {name: 행 수}를 돌려준다."""

    candidates = registry.get("candidates") or []
    if not candidates:
        raise SystemExit("등록된 후보가 없습니다 — configs/benchmark/judging_candidates.yaml의 candidates에 추가하세요.")
    names = [c["name"] for c in candidates]
    bad = [n for n in names if not NAME_PATTERN.fullmatch(n)]
    if bad or len(set(names)) != len(names):
        raise SystemExit(f"후보 이름이 잘못됐거나 중복입니다: {bad or sorted(n for n in names if names.count(n) > 1)}")

    depth = int(registry.get("depth", 10))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for cand in candidates:
        parts = []
        for split in registry.get("splits", ["val", "test"]):
            if not cand.get(split):
                raise SystemExit(f"{cand['name']}: {split} run 경로가 없습니다.")
            run = pd.read_csv(cand[split], encoding="utf-8-sig")
            missing_cols = set(RUN_COLUMNS) - set(run.columns)
            if missing_cols:
                raise SystemExit(f"{cand[split]}: 컬럼 없음 {sorted(missing_cols)}")
            qids = set(active.loc[active["split"] == split, "query_id"].astype(str))
            run = run[run["query_id"].astype(str).isin(qids)]
            covered = run[run["rank"] <= depth].groupby("query_id").size()
            short = sorted(q for q in qids if covered.get(q, 0) < depth)
            if short:
                raise SystemExit(f"{cand['name']} {split}: 상위 {depth}개가 안 되는 쿼리 {len(short)}개(예: {short[:3]})")
            parts.append(run[run["rank"] <= KEEP_DEPTH])
        merged = pd.concat(parts, ignore_index=True)[RUN_COLUMNS].assign(system=cand["name"])
        merged.sort_values(["query_id", "rank"]).to_csv(out_dir / f"{cand['name']}.csv", index=False,
                                                        encoding="utf-8-sig", lineterminator="\n")
        written[cand["name"]] = len(merged)
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--registry", default="configs/benchmark/judging_candidates.yaml")
    parser.add_argument("--make", action="store_true", help="판정 시트를 실제로 만든다(없으면 건수만 출력)")
    parser.add_argument("--reason", default="docs/EVALUATION_POLICY.md 3절 최종 후보 일괄 판정")
    args = parser.parse_args()

    config = load_config(args.config)
    registry = yaml.safe_load(Path(args.registry).read_text(encoding="utf-8"))
    active = load_active_queries(Path(config["benchmark_dir"]))
    out_dir = Path("results/judging_candidates") / registry["round"]
    written = collect_candidates(registry, active, out_dir)
    for name, rows in written.items():
        print(f"[후보] {name}: {rows}행 → {out_dir / (name + '.csv')}")

    command = [sys.executable, "scripts/16_supplemental_round.py", "make-runs", "--config", args.config,
               "--round", registry["round"], "--runs-dir", str(out_dir), "--depth", str(registry.get("depth", 10)),
               "--splits", *registry.get("splits", ["val", "test"]), "--reason", args.reason]
    if not args.make:
        command.append("--dry-run")
    raise SystemExit(subprocess.call(command))


if __name__ == "__main__":
    main()
