"""X2+X3 판정 라운드 — 10km 확장·지역 필터·지도 화면 범위(docs/SERVICE_PIPELINE_PLAN.md 11-4, 11-9).

지금 판정은 사례 위치 2km 안뿐이라 10km 확장 결과, 원격 사용자의 지역 검색 결과, 지도 화면(5km) 결과는 대부분 판정되지 않았다.
주 평가셋 사례(dev+test)마다 '요청'을 만들어 그 요청의 후보 범위에서 1단계 시스템(v1 임베딩 + 문자 BM25) 상위를 뽑고, 새 쌍만 판정한다.

요청 종류(kind)
  expand        사례 위치 그대로, 반경 10km(채점 1km·10km) — X2 반경 확장
  region_point  원격 사용자(서울시청, 사례가 서울 근처면 부산시청)가 같은 쿼리를 검색할 때 쿼리 이해가 고른 좁은 지역(동·역·시장)의
                중심에서 반경 10km(채점 1km·10km) — X3
  region_area   같은 상황에서 넓은 지역(시도·시군구·읍면) — 법정동 코드 앞자리 필터 — X3
  map5          업종 쿼리(쿼리 이해 intent=category) 사례 위치 중심 5km×5km 화면 — 지도 모드(X3). 1km 화면은 이미 판정된 1km 원 안이라 뺀다

단계
  python scripts/build_x23_round.py export            # 요청표 + Colab 입력(colab_upload/service_eval_x23/)
  (Colab) colab/service_dense_runs.ipynb — SETS=["service_eval_x23"], MODELS는 bge_m3_ft_mj만
          → service_runs_v2/runs_x23/bge_m3_ft_mj_20261014_0743.csv를 benchmark/service_ko_v1/runs_x23/에
  python scripts/build_x23_round.py runs              # 로컬 문자 BM25 run(같은 후보 범위)
  python scripts/build_x23_round.py pool --dry-run    # 판정 건수(종류·depth별)
  python scripts/build_x23_round.py pool --round service_v11 --depth 10

필터 요청(region_area·map5)만 Colab에서 다시 돌릴 때(2026-11-04 — 처음 실행이 필터 없는 옛 노트북이었다):
  python scripts/build_x23_round.py export --filtered-only   # colab_upload/service_eval_x23f/ → runs_x23f/
  필터 요청의 임베딩 결과는 runs_x23f가 있으면 그것을 쓰고 runs_x23의 같은 요청 행은 버린다. 요청 범위 밖 행이 하나라도 있으면
  판정 라운드를 만들지 않는다.

판정 대상(pool): 평가할 정책 변형이 실제로 상위 depth에 올리는 가게(TREC pooling — 평가하는 시스템의 상위를 판정한다).
변형 = 1단계(v1 + 문자 BM25 후보 합집합, 상호 일치·별칭 가산점, 브랜드 거리순)의 유사도순, 반경 요청은 거리 감쇠(점수 × 2^(−거리/h),
h = 2km·5km — Lv et al. SIGIR 2012의 거리에 따른 클릭률 감소를 반영한 정렬 후보)를 더한다.
판정은 (쿼리, 가맹점) 단위·위치 무관이라 앞 라운드에서 판정한 쌍은 다시 판정하지 않는다(build_service_pool과 같음).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_service_pool import (
    DOC_TEXT_COLUMN,
    previously_judged,
    write_annotation_xlsx,
    write_run,
)

from store_search_ai.data.service_pool import (
    annotation_sheet,
    assign_annotators,
    branch_suffixes,
    candidates_filtered,
    distances_km,
    double_annotation_queries,
    lexical_query,
    pool_pairs,
    top_k_run,
)
from store_search_ai.evaluation.service_eval import (
    apply_eval_bundle,
    load_bundle_overrides,
)
from store_search_ai.pipeline.common import load_config, sha256_file
from store_search_ai.query.understanding import QueryUnderstanding, load_gazetteer
from store_search_ai.retrieval.lexical import build_pool_document_texts, fit_bm25_scorer

logger = logging.getLogger(__name__)
SET_DIR = Path("colab_upload/service_eval_x23")
RUN_DIR = "runs_x23"
MAX_KM = 10.0           # 회의 확정 최대 반경
RADII = [1.0, MAX_KM]   # 반경 요청은 반경마다 상위 run_depth개
MAP_HALF_KM = 2.5       # 지도 화면 5km × 5km
REMOTE = [(37.5663, 126.9779), (35.1798, 129.0750)]   # 서울시청, 부산시청(eval_query_understanding.py와 같음)
DENSE = "bge_m3_ft_mj_20261014_0743"
FILTERED_SET_DIR = Path("colab_upload/service_eval_x23f")
FILTERED_RUN_DIR = "runs_x23f"
P0_SET_DIR = Path("colab_upload/service_eval_x23p0")   # P0(2026-11-05) 쿼리 이해 수정으로 범위가 바뀐 요청만
P0_RUN_DIR = "runs_x23p0"


def p0_requests(bdir: Path) -> set[str]:
    path = bdir / "x23" / "requests_p0.csv"
    return set(pd.read_csv(path, encoding="utf-8-sig")["query_id"]) if path.exists() else set()


def p0_pending(bdir: Path) -> set[str]:
    """P0으로 범위가 바뀌었는데 아직 새 임베딩 run(runs_x23p0)이 없는 요청 — 평가·판정에서 뺀다."""

    ids = p0_requests(bdir)
    d = bdir / P0_RUN_DIR
    have = set()
    for p in d.glob("*.csv") if d.exists() else []:
        have |= set(pd.read_csv(p, encoding="utf-8-sig", usecols=["query_id"])["query_id"])
    return ids - have
DECAY_HALF_KM = (2.0, 5.0)   # 거리 감쇠 정렬 후보(반경 요청)


def km(lat1, lon1, lat2, lon2) -> float:
    a, b = np.radians([lat1, lon1]), np.radians([lat2, lon2])
    h = np.sin((b[0] - a[0]) / 2) ** 2 + np.cos(a[0]) * np.cos(b[0]) * np.sin((b[1] - a[1]) / 2) ** 2
    return float(2 * 6371.0 * np.arcsin(np.sqrt(h)))


def load_corpus(bench: dict) -> pd.DataFrame:
    c = pd.read_parquet(bench["corpus_path"], columns=["doc_id", "store_name", "item_text", "address", "market_name",
                                                       "source_region", "legal_dong_code", "latitude", "longitude",
                                                       "geo_status", DOC_TEXT_COLUMN])
    return c[c["geo_status"] == "VALID"].reset_index(drop=True)


def build_requests(cfg: dict, corpus: pd.DataFrame) -> pd.DataFrame:
    bdir = Path(cfg["judging"]["benchmark_dir"])
    inst = pd.read_csv(bdir / "instances.csv", encoding="utf-8-sig", keep_default_na=False)
    inst = apply_eval_bundle(inst, load_bundle_overrides(cfg["eval_set"].get("bundle_overrides")))
    main_ids = set(pd.read_csv(cfg["eval_set"]["output"], encoding="utf-8-sig")["instance_id"])
    inst = inst[inst["instance_id"].isin(main_ids)].reset_index(drop=True)
    qu = QueryUnderstanding(corpus, gazetteer=load_gazetteer())
    rows = []
    for r in inst.itertuples():
        la, lo = float(r.latitude), float(r.longitude)
        p = qu.parse(r.query, la, lo)
        base = {"base_query_id": r.query_id, "instance_id": r.instance_id, "query": r.query, "split": r.split,
                "bundle": r.bundle, "intent": p.intent}
        rows.append({**base, "query_id": f"{r.instance_id}~x10", "kind": "expand", "region_text": p.region_text,
                     "latitude": la, "longitude": lo, "code_prefix": "", "bbox": ""})
        far = REMOTE[1] if km(la, lo, *REMOTE[0]) < 100 else REMOTE[0]
        f = qu.parse(r.query, *far)
        if f.region is not None and not f.name_first:
            area = f.region.scope == "area"
            rows.append({**base, "query_id": f"{r.instance_id}~rr", "kind": "region_area" if area else "region_point",
                         "region_text": f.region_text, "latitude": f.region.center[0], "longitude": f.region.center[1],
                         "code_prefix": f.region.code_prefix if area else "", "bbox": ""})
        if p.intent == "category" and p.region is None:
            dlat = MAP_HALF_KM / 111.0
            dlon = MAP_HALF_KM / (111.0 * np.cos(np.radians(la)))
            rows.append({**base, "query_id": f"{r.instance_id}~m5", "kind": "map5", "region_text": "",
                         "latitude": la, "longitude": lo, "code_prefix": "",
                         "bbox": f"{la - dlat:.6f},{lo - dlon:.6f},{la + dlat:.6f},{lo + dlon:.6f}"})
    return pd.DataFrame(rows)


def export(cfg: dict, bench: dict, filtered_only: bool = False, p0: bool = False) -> None:
    corpus = load_corpus(bench)
    bdir = Path(cfg["judging"]["benchmark_dir"])
    if p0:              # 요청표는 이미 고쳐 둠(requests_p0.csv의 행만) — 그 요청만 내보낸다
        req = load_requests(cfg)
        req = req[req["query_id"].isin(p0_requests(bdir))].reset_index(drop=True)
        set_dir, run_dir = P0_SET_DIR, P0_RUN_DIR
    elif filtered_only:   # 요청표는 그대로 두고 필터 요청만 다시 내보낸다(요청 ID·위치가 바뀌면 안 됨)
        req = load_requests(cfg)
        req = req[(req["code_prefix"] != "") | (req["bbox"] != "")].reset_index(drop=True)
        set_dir, run_dir = FILTERED_SET_DIR, FILTERED_RUN_DIR
    else:
        req = build_requests(cfg, corpus)
        (bdir / "x23").mkdir(parents=True, exist_ok=True)
        req.to_csv(bdir / "x23" / "requests.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
        set_dir, run_dir = SET_DIR, RUN_DIR
    cands = candidates_filtered(req, corpus, MAX_KM)
    idx = np.unique(np.concatenate(list(cands.values())))
    set_dir.mkdir(parents=True, exist_ok=True)
    docs = corpus.iloc[idx][["doc_id", DOC_TEXT_COLUMN, "latitude", "longitude", "legal_dong_code"]]
    docs.rename(columns={DOC_TEXT_COLUMN: "text"}).to_csv(set_dir / "docs.csv", index=False, encoding="utf-8-sig",
                                                         lineterminator="\n")
    req[["query_id", "query", "latitude", "longitude", "code_prefix", "bbox"]].to_csv(
        set_dir / "queries.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    meta = {"judge_radius_km": MAX_KM, "run_depth": cfg["judging"]["run_depth"], "report_radii_km": RADII, "run_dir": run_dir,
            "docs": len(docs), "queries": len(req), "doc_text": DOC_TEXT_COLUMN, "corpus_path": bench["corpus_path"],
            "filters": "code_prefix(법정동 코드 앞자리, '|' 여러 개) · bbox(south,west,north,east) — 있으면 반경 대신"}
    (set_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("요청 %s, 가맹점 %d개 → %s (Drive store-search-ai/%s/에 올림)", req["kind"].value_counts().to_dict(),
                len(docs), set_dir, set_dir.name)


def load_runs_x23(bdir: Path, req: pd.DataFrame) -> pd.DataFrame:
    """runs_x23(+ 필터 요청은 runs_x23f가 있으면 그것)을 읽는다."""

    frames = [pd.read_csv(p, encoding="utf-8-sig") for p in sorted((bdir / RUN_DIR).glob("*.csv"))]
    if not frames:
        raise SystemExit("run이 없습니다 — 먼저 runs")
    runs = pd.concat(frames, ignore_index=True)
    fdir = bdir / FILTERED_RUN_DIR
    if fdir.exists() and any(fdir.glob("*.csv")):
        filtered = set(req.loc[(req["code_prefix"] != "") | (req["bbox"] != ""), "query_id"])
        redo = pd.concat([pd.read_csv(p, encoding="utf-8-sig") for p in sorted(fdir.glob("*.csv"))], ignore_index=True)
        drop = runs["query_id"].isin(filtered) & runs["system"].isin(set(redo["system"]))
        runs = pd.concat([runs[~drop], redo[redo["query_id"].isin(filtered)]], ignore_index=True)
    pdir = bdir / P0_RUN_DIR                               # P0으로 범위가 바뀐 요청의 새 임베딩 run이 있으면 그것
    if pdir.exists() and any(pdir.glob("*.csv")):
        redo = pd.concat([pd.read_csv(p, encoding="utf-8-sig") for p in sorted(pdir.glob("*.csv"))], ignore_index=True)
        ids = p0_requests(bdir) & set(redo["query_id"])
        drop = runs["query_id"].isin(ids) & runs["system"].isin(set(redo["system"]))
        runs = pd.concat([runs[~drop], redo[redo["query_id"].isin(ids)]], ignore_index=True)
    return runs


def in_range(frame: pd.DataFrame, req: pd.DataFrame, corpus: pd.DataFrame) -> np.ndarray:
    """행(query_id = 요청, doc_id)이 그 요청의 후보 범위(필터 또는 반경 10km) 안인가."""

    from store_search_ai.data.service_pool import filter_mask, haversine_km

    c = corpus.set_index("doc_id")
    q = req.set_index("query_id")
    ok = np.zeros(len(frame), dtype=bool)
    for qid, ix in frame.groupby("query_id").indices.items():
        d = c.loc[frame["doc_id"].to_numpy()[ix]]
        row = q.loc[qid]
        lats, lons = d["latitude"].to_numpy(float), d["longitude"].to_numpy(float)
        m = filter_mask(row["code_prefix"], row["bbox"], d["legal_dong_code"].astype(str).to_numpy(), lats, lons)
        if m is None:
            m = haversine_km(float(row["latitude"]), float(row["longitude"]), lats, lons) <= MAX_KM + 1e-6
        ok[ix] = m
    return ok


def clean_runs(raw: pd.DataFrame, req: pd.DataFrame, corpus: pd.DataFrame, bdir: Path) -> tuple[pd.DataFrame, set, dict]:
    """요청 범위 밖 run 행 처리. x23/requests_changed.csv에 적힌 요청(Colab 실행 뒤 지명 사전 수정으로 범위가 바뀜)은 범위 밖 행만
    버리고, 그 밖의 범위 밖 행이 있는 요청은 통째로 뺀다(필터 없는 옛 노트북 결과처럼 순위 자체가 틀린 경우). 반환: (run, 뺀 요청, 기록)."""

    changed_path = bdir / "x23" / "requests_changed.csv"
    changed = set(pd.read_csv(changed_path, encoding="utf-8-sig")["query_id"]) if changed_path.exists() else set()
    bad = ~in_range(raw, req, corpus)
    drop_rows = bad & raw["query_id"].isin(changed).to_numpy()
    stale = set(raw.loc[bad & ~drop_rows, "query_id"])
    if stale:
        by = raw[bad & ~drop_rows].merge(req[["query_id", "kind"]], on="query_id").groupby(["system", "kind"]).size()
        logger.warning("요청 범위 밖 run 행이 있는 요청 %d개(시스템·종류별 행 %s)는 뺀다 — 필터 없는 옛 노트북 결과 등",
                       len(stale), by.to_dict())
    out = raw[~drop_rows & ~raw["query_id"].isin(stale)]
    dense_missing = sorted(set(req["query_id"]) - stale - set(out.loc[out["system"] == DENSE, "query_id"]))
    notes = {"changed_requests_rows_dropped": int(drop_rows.sum()), "changed_requests": sorted(changed),
             "dense_missing_requests": dense_missing}
    if dense_missing:
        logger.warning("임베딩 결과가 없는 요청 %d개(BM25만): %s", len(dense_missing), dense_missing[:10])
    return out, stale, notes


def policy_runs(runs: pd.DataFrame, req: pd.DataFrame, corpus: pd.DataFrame, category_gamma: float = 0.0,
                categories: pd.Series | None = None, expansion: dict | None = None,
                cosine: dict | None = None) -> dict[str, pd.DataFrame]:
    """평가할 정책 변형의 순위: 1단계(11-8 채택 — v1+문자 BM25 합집합, 상호 일치·별칭 가산점, 브랜드 거리순)의 유사도순,
    반경 요청은 거리 감쇠(h = 2·5km)도. query_id = 요청 ID.
    category_gamma > 0이면 업종 쿼리에 업종 가산점(γ × 1단계 상위 10개 업종 분포에서 그 가게 업종의 비중, 11-15)을 더한 순서를 'sim'으로,
    가산점 전 순서를 'sim_base'로 돌려준다 — 관련 확률(X1)은 가산점 전 점수로 계산한다.
    expansion = {"w", "texts"(기준 쿼리 ID → 확장어), "bm25"(corpus와 같은 행 순서의 SparseBM25)}이면 업종 의도 요청에 LLM 쿼리 확장
    점수를 더한다(11-18, retrieval/expansion.py). 확장은 1단계의 일부라 'sim_base'에도 들어간다(확장으로 들어온 가게도 관련 확률을 받는다)."""

    from eval_service_pipeline import alias_name_hits, brand_distance_sort, union_v1

    from store_search_ai.data.service_pool import haversine_km
    from store_search_ai.query.aliases import BrandAliases
    from store_search_ai.retrieval.fusion import _rerank, boost

    qu = QueryUnderstanding(corpus, gazetteer=load_gazetteer())
    parsed = []
    for r in req.itertuples():
        p = qu.parse(r.query, float(r.latitude), float(r.longitude))
        parsed.append({"instance_id": r.query_id, "name_key": p.name_key, "core": p.core, "intent": p.intent})
    parsed = pd.DataFrame(parsed)
    aliases = BrandAliases.load()
    names = corpus.set_index("doc_id")["store_name"]
    v1, bm25 = runs[runs["system"] == DENSE], runs[runs["system"] == "char_bm25"]
    frames: list[pd.DataFrame] = []
    if expansion is not None and expansion["w"] > 0:
        from store_search_ai.retrieval.expansion import expansion_frame

        cat_req = req[req["query_id"].isin(set(parsed.loc[parsed["intent"] == "category", "instance_id"]))]
        cands = candidates_filtered(cat_req, corpus, expansion.get("km", MAX_KM))
        doc_ids = corpus["doc_id"].to_numpy()
        frames = [expansion_frame(r.query_id, expansion["texts"].get(r.base_query_id, ""), expansion["bm25"], cands[r.query_id],
                                  doc_ids) for r in cat_req.itertuples()]
        frames = [f for f in frames if f is not None]
    if cosine is not None:   # P2(a): BM25·확장으로만 들어온 후보에도 실제 v1 코사인(서비스와 같게)
        from eval_service_pipeline import augment_v1

        extra = pd.concat([bm25[["query_id", "doc_id"]], *[f[["query_id", "doc_id"]] for f in frames]], ignore_index=True)
        v1 = augment_v1(v1, extra, dict(zip(req["query_id"], req["base_query_id"], strict=True)), cosine)
    union = union_v1(v1, bm25)
    cores = dict(zip(parsed["instance_id"], parsed["name_key"], strict=True))
    stage = boost(union, alias_name_hits(union, cores, names, aliases), 0.5, "stage1")
    if frames:
        from eval_service_pipeline import BRAND_MIN

        from store_search_ai.retrieval.expansion import add_expansion

        stage = add_expansion(stage, pd.concat(frames, ignore_index=True), expansion["w"], "stage1", BRAND_MIN)
    geo = corpus[["doc_id", "store_name", "latitude", "longitude"]]
    loc = req[["query_id", "latitude", "longitude"]].rename(columns={"query_id": "instance_id"})   # 요청 ID = 사례 자리

    def finish(st: pd.DataFrame) -> pd.DataFrame:
        st = brand_distance_sort(st, loc, parsed, geo, aliases, MAX_KM, "stage1")
        st = st[in_range(st, req, corpus)]                     # 브랜드 지점 찾기가 필터 밖을 더하지 않게
        return st.sort_values(["query_id", "rank"]).assign(rank=lambda d: d.groupby("query_id").cumcount() + 1)

    out = {"sim_base": finish(stage)}
    if category_gamma > 0 and categories is not None:
        from store_search_ai.retrieval.category_boost import category_share

        share = category_share(stage, categories)
        cat_q = set(parsed.loc[~parsed["intent"].isin(["name", "brand"]), "instance_id"])
        add = share.to_numpy() * stage["query_id"].isin(cat_q).to_numpy()
        stage = _rerank(stage.assign(score=stage["score"] + category_gamma * add)[["query_id", "doc_id", "score"]], "stage1")
    out["sim"] = finish(stage) if category_gamma > 0 and categories is not None else out["sim_base"]
    stage = out["sim"]
    circle = set(req.loc[req["kind"].isin(["expand", "region_point"]), "query_id"])
    s = stage[stage["query_id"].isin(circle)].copy()
    loc = req.set_index("query_id")[["latitude", "longitude"]]
    c = corpus.set_index("doc_id")[["latitude", "longitude"]]
    a = loc.loc[s["query_id"]].to_numpy(float)
    b = c.loc[s["doc_id"]].to_numpy(float)
    dist = np.array([float(haversine_km(x[0], x[1], np.array([y[0]]), np.array([y[1]]))[0]) for x, y in zip(a, b, strict=True)])
    for h in DECAY_HALF_KM:
        out[f"decay{h:g}"] = _rerank(s.assign(score=s["score"] * np.power(2.0, -dist / h))[["query_id", "doc_id", "score"]],
                                     f"decay{h:g}")
    return out


def load_expansion(w: float, llm: str, corpus: pd.DataFrame) -> dict | None:
    """policy_runs의 expansion 인자(11-18). w = 0이면 None."""

    if not w:
        return None
    from store_search_ai.retrieval.expansion import SparseBM25, load_expansions

    path = Path("results/service_pipeline/x8") / f"expansions_{llm}.csv"
    logger.info("LLM 쿼리 확장 w = %.2f (%s), 문자 BM25 색인 %d곳", w, path, len(corpus))
    return {"w": w, "texts": load_expansions(path), "bm25": SparseBM25(build_pool_document_texts(corpus))}


def load_requests(cfg: dict) -> pd.DataFrame:
    path = Path(cfg["judging"]["benchmark_dir"]) / "x23" / "requests.csv"
    if not path.exists():
        raise SystemExit("요청표가 없습니다 — 먼저 export")
    return pd.read_csv(path, encoding="utf-8-sig", keep_default_na=False)


def runs(cfg: dict, bench: dict) -> None:
    corpus = load_corpus(bench)
    req = load_requests(cfg)
    cands = candidates_filtered(req, corpus, MAX_KM)
    dist = distances_km(req, corpus, cands)
    idx = np.unique(np.concatenate(list(cands.values())))
    texts = build_pool_document_texts(corpus).to_numpy()
    pos = np.full(len(corpus), -1)
    pos[idx] = np.arange(len(idx))
    logger.info("char BM25 색인: %d개", len(idx))
    bm25 = fit_bm25_scorer(pd.Series(texts[idx]))
    branch = branch_suffixes(corpus)                     # 지점 접미사는 BM25 쿼리에서 뺀다(P0)
    doc_ids = corpus["doc_id"].to_numpy()
    depth = cfg["judging"]["run_depth"]
    frames = []
    for r in req.itertuples():
        filtered = bool(r.code_prefix or r.bbox)
        c = cands[r.query_id]
        frames.append(top_k_run(r.query_id, c, bm25(lexical_query(r.query, r.region_text, branch))[pos[c]], doc_ids, depth, "char_bm25",
                                None if filtered else dist[r.query_id], None if filtered else RADII))
    run_dir = Path(cfg["judging"]["benchmark_dir"]) / RUN_DIR
    run_dir.mkdir(parents=True, exist_ok=True)
    write_run(pd.concat(frames, ignore_index=True), run_dir / "char_bm25.csv")
    if not (run_dir / f"{DENSE}.csv").exists():
        logger.warning("%s run이 없음 — Colab에서 만들어 %s에 넣을 것", DENSE, run_dir)


def pool(args, cfg: dict, bench: dict) -> None:
    bdir = Path(cfg["judging"]["benchmark_dir"])
    req = load_requests(cfg)
    run_dir = bdir / RUN_DIR
    files = sorted(run_dir.glob("*.csv")) + sorted((bdir / FILTERED_RUN_DIR).glob("*.csv"))
    raw = load_runs_x23(bdir, req)
    systems = sorted(raw["system"].unique())
    corpus = load_corpus(bench)
    if DENSE not in systems:
        raise SystemExit("임베딩 run이 없습니다")
    raw, stale, notes = clean_runs(raw, req, corpus, bdir)
    stale = stale | p0_pending(bdir)                      # P0 새 임베딩 run을 기다리는 요청은 판정하지 않는다
    raw = raw[~raw["query_id"].isin(stale)]
    expansion = load_expansion(args.expansion_w, args.llm, corpus)
    all_runs = pd.concat([r.assign(system=k) for k, r in policy_runs(raw, req, corpus, expansion=expansion).items()],
                         ignore_index=True)
    judged = previously_judged(bdir)
    to_base = dict(zip(req["query_id"], req["base_query_id"], strict=True))
    kind = dict(zip(req["query_id"], req["kind"], strict=True))

    def new_pairs(depth: int) -> pd.DataFrame:
        p = pool_pairs(all_runs, depth).rename(columns={"query_id": "request_id"})
        p["query_id"] = p["request_id"].map(to_base)
        p["kind"] = p["request_id"].map(kind)
        p = p[[(q, d) not in judged for q, d in zip(p["query_id"], p["doc_id"], strict=True)]]
        return (p.groupby(["query_id", "doc_id"], as_index=False)
                .agg(pool_sources=("pool_sources", lambda s: "|".join(sorted(set("|".join(s).split("|"))))),
                     instance_ids=("request_id", lambda s: "|".join(sorted(set(s)))),
                     kinds=("kind", lambda s: "|".join(sorted(set(s))))))

    rows = []
    for d in sorted({5, 10, args.depth or 10}):
        p = new_pairs(d)
        by_kind = {k: int(p["kinds"].str.contains(k).sum()) for k in ["expand", "region_point", "region_area", "map5"]}
        rows.append({"depth": d, "새 판정 쌍": len(p), "쿼리 수": p["query_id"].nunique(), **by_kind})
    ok_req = req[~req["query_id"].isin(stale)]
    print(f"========== 판정 건수(정책 변형 {sorted(all_runs['system'].unique())}, 판정 가능한 요청 "
          f"{ok_req['kind'].value_counts().to_dict()}, 범위 밖 결과로 뺀 요청 {len(stale)}) ==========")
    print(pd.DataFrame(rows).to_string(index=False))
    share = cfg["judging"]["double_annotation_share"]
    print(f"(쿼리의 {share:.0%}는 A·B 두 명이 판정 — 사람 판정 건수는 그만큼 더 많음. 종류별 수는 겹침 포함)")
    if args.dry_run:
        return
    if not args.round:
        raise SystemExit("--round가 필요합니다.")
    if stale and not args.allow_partial:
        raise SystemExit(f"범위 밖 결과가 있는 요청 {len(stale)}개 — runs_x23f를 넣거나, 나머지 요청만 먼저 판정하려면 --allow-partial")
    round_dir = bdir / "annotations" / args.round
    if (round_dir / "pool_manifest.json").exists():
        raise SystemExit(f"{round_dir}에 이미 라운드가 있습니다 — 다른 --round를 쓰세요.")
    depth = args.depth or 10
    pairs = new_pairs(depth)
    seed = cfg["random_seed"]
    base = pd.read_csv(cfg["import"]["output"], encoding="utf-8-sig", keep_default_na=False)
    sheet = annotation_sheet(pairs[["query_id", "doc_id", "pool_sources", "instance_ids"]], base, corpus, seed)
    double = double_annotation_queries(sorted(pairs["query_id"].unique()), share, seed)
    writers = {qid: set(str(w).split("|")) for qid, w in zip(base["query_id"], base["writers"], strict=True)}
    jcfg = cfg["judging"]
    assignment = assign_annotators(pairs.groupby("query_id").size(), double, jcfg["annotators"], writers, seed)
    round_dir.mkdir(parents=True, exist_ok=True)
    for name, qids in assignment.items():
        part = sheet[sheet["query_id"].isin(qids)].reset_index(drop=True)
        part.to_csv(round_dir / f"annotation_{name}.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
        write_annotation_xlsx(part, round_dir / f"판정_{name}.xlsx")
        logger.info("판정자 %s: 쿼리 %d개(이중 판정 %d 포함), %d쌍", name, len(qids), len(double), len(part))
    pairs.to_csv(round_dir / "pool.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    manifest = {
        "round": args.round, "set": "x23", "created_at": datetime.now(UTC).isoformat(),
        "reused_judgments": "판정은 (쿼리, 가맹점) 단위·위치 무관 — 앞 라운드에서 판정한 쌍은 다시 판정하지 않음",
        "requests": ok_req["kind"].value_counts().to_dict(), "excluded_requests": sorted(stale), **notes,
        "pool": "정책 변형(1단계 유사도순, 반경 요청은 거리 감쇠 h=2·5km) 상위 depth",
        "expansion": {"w": args.expansion_w, "llm": args.llm} if args.expansion_w else None, "max_km": MAX_KM, "radii_km": RADII, "map_half_km": MAP_HALF_KM,
        "depth": depth, "queries": int(pairs["query_id"].nunique()), "pairs": len(pairs),
        "pairs_by_kind": {k: int(pairs["kinds"].str.contains(k).sum()) for k in ["expand", "region_point", "region_area", "map5"]},
        "double_annotation_queries": len(double), "double_annotation_pairs": int(sheet["query_id"].isin(double).sum()),
        "annotators": {name: {"writer_id": jcfg["annotators"][name], "queries": len(qids),
                              "pairs": int(sheet["query_id"].isin(qids).sum())} for name, qids in assignment.items()},
        "runs_sha256": {f"{p.parent.name}/{p.name}": sha256_file(p) for p in files},
        "requests_sha256": sha256_file(bdir / "x23" / "requests.csv"),
        "guideline": "docs/SERVICE_ANNOTATION_GUIDELINE.md",
    }
    (round_dir / "pool_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("저장: %s (전체 %d쌍, 이중 판정 %d쌍)", round_dir, len(sheet), manifest["double_annotation_pairs"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["export", "runs", "pool"])
    parser.add_argument("--round", help="pool: 판정 라운드 이름(예: service_v11)")
    parser.add_argument("--depth", type=int, help="pool: 요청·시스템마다 상위 몇 개를 판정할지(기본 10)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--filtered-only", action="store_true", help="export: 필터 요청만 다시(colab_upload/service_eval_x23f)")
    parser.add_argument("--p0", action="store_true", help="export: P0으로 범위가 바뀐 요청만(colab_upload/service_eval_x23p0)")
    parser.add_argument("--expansion-w", type=float, default=0.0, help="pool: LLM 쿼리 확장을 붙인 정책 목록으로(11-18)")
    parser.add_argument("--llm", default="Qwen2.5-14B-Instruct", help="pool: 확장 파일 results/service_pipeline/x8/expansions_<llm>.csv")
    parser.add_argument("--allow-partial", action="store_true", help="pool: 범위 밖 결과가 있는 요청을 빼고 라운드를 만든다")
    parser.add_argument("--config", default="configs/query/service_queryset_v1.yaml")
    parser.add_argument("--benchmark-config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config(args.config)
    bench = load_config(args.benchmark_config)
    {"export": lambda: export(cfg, bench, args.filtered_only, args.p0), "runs": lambda: runs(cfg, bench), "pool": lambda: pool(args, cfg, bench)}[args.command]()


if __name__ == "__main__":
    main()
