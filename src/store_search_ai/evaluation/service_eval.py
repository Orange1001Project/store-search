"""서비스셋 채점 — 사례(쿼리 × 가정위치)마다 반경 R km 안의 결과만으로 지표를 낸다(docs/SERVICE_ANNOTATION_GUIDELINE.md).

- 반경 안 정답(2점 이상)이 하나도 없는 사례는 순위 지표에서 뺀다(TREC 관례: 정답 없는 토픽은 nDCG 평균에서 제외). 개수는 따로 센다.
- 이상적인 순위(IDCG)는 그 반경 안 판정된 가맹점으로만 만든다 — 반경 밖 정답은 서비스에서 보이지 않으므로.
- nDCG@10·Judged@10은 공식 evaluator와 같은 ir_measures로 계산한다. bad@3 = 상위 3개에 정답이 없음, top1_ok = 1위가 정답.
- run은 판정 반경(2km) 안 상위 run_depth개다. 1km 지표는 그 목록에서 1km 안만 남겨 순위를 다시 매긴다.
"""

from __future__ import annotations

import ir_measures
import numpy as np
import pandas as pd

from store_search_ai.data.service_pool import haversine_km
from store_search_ai.evaluation import (
    evaluator as _ir_compat,  # noqa: F401  — Python 3.12+용 ir_measures 패치를 먼저 적용
)

BINARY_THRESHOLD = 2
MEASURES = [ir_measures.parse_measure("nDCG@10"), ir_measures.parse_measure("Judged@10")]


def attach_distance(frame: pd.DataFrame, instances: pd.DataFrame, coords: pd.DataFrame, key: str = "instance_id") -> pd.DataFrame:
    loc = instances.set_index("instance_id")[["latitude", "longitude"]]
    c = coords.set_index("doc_id")[["latitude", "longitude"]]
    f = frame[frame[key].isin(loc.index) & frame["doc_id"].isin(c.index)].copy()
    q, d = loc.loc[f[key]].to_numpy(float), c.loc[f["doc_id"]].to_numpy(float)
    a, b = np.radians(q), np.radians(d)
    h = np.sin((b[:, 0] - a[:, 0]) / 2) ** 2 + np.cos(a[:, 0]) * np.cos(b[:, 0]) * np.sin((b[:, 1] - a[:, 1]) / 2) ** 2
    f["dist_km"] = 2 * 6371.0 * np.arcsin(np.sqrt(h))
    return f


def instance_qrels(instances: pd.DataFrame, qrels: pd.DataFrame, coords: pd.DataFrame) -> pd.DataFrame:
    """쿼리 판정을 사례로 펼치고 거리를 붙인다(판정은 위치와 무관)."""

    expanded = instances[["instance_id", "query_id"]].merge(qrels, on="query_id")
    return attach_distance(expanded, instances, coords)


def score_system(run: pd.DataFrame, iq: pd.DataFrame, instances: pd.DataFrame, coords: pd.DataFrame,
                 radius_km: float) -> pd.DataFrame:
    """사례별 지표(nDCG@10, Judged@10, bad@3, top1_ok, 정답 수). run의 query_id 열은 사례 ID다."""

    r = attach_distance(run.rename(columns={"query_id": "instance_id"}), instances, coords)
    r = r[r["dist_km"] <= radius_km].sort_values(["instance_id", "rank"])
    r = r.assign(rank=r.groupby("instance_id").cumcount() + 1)
    q = iq[iq["dist_km"] <= radius_km]
    n_rel = q[q["relevance"] >= BINARY_THRESHOLD].groupby("instance_id").size()
    answerable = set(n_rel.index)

    qrels = [ir_measures.Qrel(i, d, int(g)) for i, d, g in zip(q["instance_id"], q["doc_id"], q["relevance"], strict=True)
             if i in answerable]
    scored = [ir_measures.ScoredDoc(i, d, float(-k)) for i, d, k in zip(r["instance_id"], r["doc_id"], r["rank"], strict=True)
              if i in answerable]
    rows: dict[str, dict] = {i: {} for i in answerable}
    for m in ir_measures.iter_calc(MEASURES, qrels, scored):
        rows[m.query_id][str(m.measure)] = float(m.value)
    rel = {(i, d): g for i, d, g in zip(q["instance_id"], q["doc_id"], q["relevance"], strict=True)}
    for i, g in r.groupby("instance_id"):
        if i not in answerable:
            continue
        grades = [rel.get((i, d), -1) for d in g["doc_id"]]
        rows[i]["bad@3"] = float(not any(x >= BINARY_THRESHOLD for x in grades[:3]))
        rows[i]["top1_ok"] = float(bool(grades) and grades[0] >= BINARY_THRESHOLD)
    out = pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "instance_id"
    for col, default in (("nDCG@10", 0.0), ("Judged@10", 0.0), ("bad@3", 1.0), ("top1_ok", 0.0)):
        if col not in out:
            out[col] = default
        out[col] = out[col].fillna(default)   # 반경 안 결과가 하나도 없으면 0점·bad
    out["n_relevant"] = n_rel.reindex(out.index).astype(int)
    return out.reset_index()


def paired(a: pd.Series, b: pd.Series, samples: int = 10_000, seed: int = 20261021) -> dict:
    """같은 사례에서 a − b의 평균 차이, 부트스트랩 95% CI, 양측 부호 뒤집기 순열검정 p."""

    d = (a - b).dropna().to_numpy(float)
    if len(d) == 0:
        return {}
    rng = np.random.default_rng(seed)
    boot = rng.choice(d, size=(samples, len(d)), replace=True).mean(axis=1)
    perm = np.abs((rng.choice([-1.0, 1.0], size=(samples, len(d))) * d).mean(axis=1))
    return {"delta": float(d.mean()), "ci_low": float(np.quantile(boot, 0.025)), "ci_high": float(np.quantile(boot, 0.975)),
            "p": float((np.sum(perm >= abs(d.mean())) + 1) / (samples + 1)), "n": len(d),
            "wins": int((d > 1e-9).sum()), "losses": int((d < -1e-9).sum())}


def no_answer_counts(instances: pd.DataFrame, iq: pd.DataFrame, radius_km: float) -> pd.Series:
    q = iq[(iq["dist_km"] <= radius_km) & (iq["relevance"] >= BINARY_THRESHOLD)]
    has = set(q["instance_id"])
    return instances.assign(answerable=instances["instance_id"].isin(has))["answerable"]


__all__ = ["attach_distance", "haversine_km", "instance_qrels", "no_answer_counts", "paired", "score_system"]
