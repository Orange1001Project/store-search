"""관련 임계값(X1, docs/SERVICE_PIPELINE_PLAN.md 11-4) — 1단계 점수를 관련 확률 P(관련)로 보정하고, 보여 줄 가게를 정하는 임계값을 고른다.

반경 확장("관련 가게 N개 미만이면 10km"), "없어요" 판단, 지도 모드(화면 안 관련 가게 전부)가 모두 이 값으로 정해진다.

- 보정: 판정된 (사례, 가게) 쌍으로 학습한다. 점수만 쓰는 isotonic 회귀(Zadrozny & Elkan, KDD 2002)와, 점수에 쿼리 안 상대값
  (그 사례 1위 점수와의 차이, 순위)을 더한 로지스틱 회귀(Platt 1999 방식), 여기에 어휘 일치(문자 BM25, 사례 안 최댓값으로 나눔)를
  더한 로지스틱 회귀를 비교한다 — 코사인 점수의 크기는 쿼리마다 달라서 절대 임계값만으로는 쿼리마다 자르는 위치가 흔들린다
  (순위 목록 자르기에 쿼리 점수 분포를 쓰는 Choppy, Bahri et al. SIGIR 2020). 로지스틱은 백엔드에서 식 하나로 옮길 수 있다.
- 평가: 쿼리 단위로 나눈 교차검증(같은 쿼리의 사례가 학습·평가에 함께 들어가지 않게)의 예측으로 log-loss·Brier·AUC·ECE를 잰다.
- 판정 안 된 쌍은 학습·정밀도에서 뺀다(condensed — Sakai 2007). 비관적 정밀도(미판정 = 오답)도 같이 낸다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

BINARY = 2   # service_eval.BINARY_THRESHOLD — 2점 이상이 정답
FEATURE_SETS = {"logistic": ["score", "gap", "log_rank"], "logistic_bm25": ["score", "gap", "log_rank", "bm25_rel"],
                # P2(b), 2026-11-09: 가게 텍스트 특성 — 정성 점검의 함정('모종' → 모녀국수(품목 없음, 상호 글자만), '다이어트 음식' →
                # 품목이 '음식'뿐인 가게)을 겨냥
                "logistic_plus": ["score", "gap", "log_rank", "bm25_rel", "kw_item", "kw_name_only", "item_words", "item_freq"]}
FEATURE_SETS["logistic_cos"] = ["score", "gap", "log_rank", "bm25_rel", "cos"]
# 2026-11-09 test 정성 점검: score는 쿼리 안 min-max라 임베딩 1위가 늘 1 → 업종 묶음에서 1위가 늘 P ≈ 0.505(맞는 가게가 없어도
# '관련'). 정규화 전 코사인(절대 크기)을 더해 '1위지만 실제로는 먼 가게'를 구분한다.
TEXT_FEATURES = ("kw_item", "kw_name_only", "item_words", "item_freq")


def add_cosine(cands: pd.DataFrame, base_of: dict, cos: dict) -> pd.DataFrame:
    """cos = 쿼리 문장과 가게의 v1 코사인(정규화 전). cos: (기준 쿼리 ID, doc_id) → 코사인(v1 run 점수 + P2(a) 쌍 코사인).
    없는 쌍은 그 사례에서 아는 코사인의 최솟값(임베딩 상위 50 밖이면 50위보다 낮다 — 위쪽 추정)으로 채운다.
    서비스(백엔드)는 모든 후보의 실제 코사인을 계산하므로 채움이 필요 없다."""

    v = np.array([cos.get((base_of.get(i), d), np.nan) for i, d in zip(cands["instance_id"], cands["doc_id"], strict=True)])
    c = cands.assign(cos=v)
    c["cos"] = c["cos"].fillna(c.groupby("instance_id")["cos"].transform("min")).fillna(0.0)
    return c


def _norm(text: object) -> str:
    return "".join(str(text or "").split()).casefold()


def store_profile(corpus: pd.DataFrame) -> pd.DataFrame:
    """가게별 텍스트 특성 재료(doc_id 색인): 정규화한 상호·품목, item_words = log(1 + 품목 단어 수),
    item_freq = log(1 + 같은 품목 문구를 가진 가게 수) — '음식'·'한식'처럼 흔한 대분류일수록 크다."""

    items = corpus["item_text"].fillna("").astype(str)
    norm_item = items.map(_norm)
    freq = norm_item.map(norm_item.value_counts())
    return pd.DataFrame({"name": corpus["store_name"].map(_norm).to_numpy(), "item": norm_item.to_numpy(),
                         "item_words": np.log1p(items.str.split(r"[\s,/·]+").map(lambda w: sum(1 for x in w if x))).to_numpy(),
                         "item_freq": np.where(norm_item == "", 0.0, np.log1p(freq)).astype(float)},
                        index=corpus["doc_id"].to_numpy())


def add_text_features(cands: pd.DataFrame, keywords: dict, profile: pd.DataFrame) -> pd.DataFrame:
    """kw_item = 쿼리 단어(지역·서술어 뺀 것) 중 하나가 품목에 있음, kw_name_only = 상호에만 있고 품목에는 없음(글자 겹침 함정),
    item_words·item_freq = store_profile. cands 열: instance_id, doc_id."""

    pr = profile.reindex(cands["doc_id"].to_numpy())
    kws = [keywords.get(i, []) for i in cands["instance_id"]]
    in_item = np.array([any(k in it for k in ks) for ks, it in zip(kws, pr["item"].fillna(""), strict=True)])
    in_name = np.array([any(k in nm for k in ks) for ks, nm in zip(kws, pr["name"].fillna(""), strict=True)])
    return cands.assign(kw_item=in_item.astype(float), kw_name_only=(in_name & ~in_item).astype(float),
                        item_words=pr["item_words"].fillna(0.0).to_numpy(), item_freq=pr["item_freq"].fillna(0.0).to_numpy())


def query_keywords_for(queries: pd.Series, region_texts: pd.Series, drop=frozenset()) -> dict:
    """사례·요청 ID → 정규화한 쿼리 단어 목록(서술어·지역·지점 접미사 뺀 lexical_query 단어)."""

    from store_search_ai.data.service_pool import lexical_query

    return {i: [_norm(w) for w in lexical_query(q, r, drop).split() if len(w) >= 2]
            for i, q, r in zip(queries.index, queries.to_numpy(), region_texts.reindex(queries.index).fillna("").to_numpy(),
                               strict=True)}


def add_features(cands: pd.DataFrame) -> pd.DataFrame:
    """사례별 후보(반경 안)에 쿼리 안 상대 특성을 붙인다: gap = 점수 − 그 사례 1위 점수(≤ 0), log_rank = log(반경 안 순위),
    bm25_rel = 문자 BM25 점수 ÷ 그 사례 최댓값(BM25 상위에 없으면 0 — bm25 열이 있을 때)."""

    c = cands.sort_values(["instance_id", "score"], ascending=[True, False]).copy()
    c["rank_r"] = c.groupby("instance_id").cumcount() + 1
    c["gap"] = c["score"] - c.groupby("instance_id")["score"].transform("max")
    c["log_rank"] = np.log(c["rank_r"])
    if "bm25" in c:
        b = c["bm25"].fillna(0.0)
        c["bm25_rel"] = b / c.assign(b=b).groupby("instance_id")["b"].transform("max").replace(0, 1)
    return c


def fit_isotonic(x: np.ndarray, y: np.ndarray):
    from sklearn.isotonic import IsotonicRegression

    return IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip").fit(x, y)


def fit_logistic(X: np.ndarray, y: np.ndarray):
    from sklearn.linear_model import LogisticRegression

    return LogisticRegression(C=1.0, max_iter=1000).fit(X, y)


def predict(model, kind: str, frame: pd.DataFrame) -> np.ndarray:
    if kind == "isotonic":
        return model.predict(frame["score"].to_numpy())
    return model.predict_proba(frame[FEATURE_SETS[kind]].to_numpy())[:, 1]


def fit(kind: str, frame: pd.DataFrame):
    y = (frame["relevance"] >= BINARY).to_numpy(int)
    if kind == "isotonic":
        return fit_isotonic(frame["score"].to_numpy(), y)
    return fit_logistic(frame[FEATURE_SETS[kind]].to_numpy(), y)


def calibration_metrics(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    from sklearn.metrics import roc_auc_score

    ok = ~np.isnan(p)
    p, y = np.clip(p[ok], 1e-6, 1 - 1e-6), y[ok]
    edges = np.minimum((p * bins).astype(int), bins - 1)
    ece = sum(abs(p[edges == b].mean() - y[edges == b].mean()) * (edges == b).sum() for b in range(bins) if (edges == b).any()) / len(p)
    return {"pairs": len(p), "positive_rate": round(float(y.mean()), 4),
            "log_loss": round(float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), 4),
            "brier": round(float(np.mean((p - y) ** 2)), 4), "auc": round(float(roc_auc_score(y, p)), 4), "ece": round(float(ece), 4)}


def instance_outcomes(cands: pd.DataFrame, answerable: set, threshold: float) -> pd.DataFrame:
    """임계값 이상만 보여 줄 때 사례별 결과. cands: instance_id, p, relevance(미판정 NaN). answerable: 반경 안 정답이 있는 사례.

    hidden = 정답이 있는데 아무것도 안 보임('헛된 없음'), miss = 보여 준 것 중 정답이 없음(헛된 없음 포함),
    false_show = 정답이 없는 사례에 뭔가 보임, precision = 보여 준 판정된 가게 중 정답 비율."""

    rows = []
    for i, g in cands.groupby("instance_id"):
        shown = g[g["p"] >= threshold]
        judged = shown["relevance"].notna()
        rel = (shown["relevance"] >= BINARY).sum()
        rows.append({"instance_id": i, "answerable": i in answerable, "n_shown": len(shown), "n_shown_relevant": int(rel),
                     "n_shown_judged": int(judged.sum()), "expected_relevant": float(g["p"].sum())})
    out = pd.DataFrame(rows)
    out["hidden"] = out["answerable"] & (out["n_shown"] == 0)
    out["miss"] = out["answerable"] & (out["n_shown_relevant"] == 0)
    out["false_show"] = ~out["answerable"] & (out["n_shown"] > 0)
    return out


def summarize_outcomes(o: pd.DataFrame) -> dict:
    ans = o[o["answerable"]]
    judged = o["n_shown_judged"].sum()
    at_least = {f"shown_ge_{k}": round(float((o["n_shown"] >= k).mean()), 4) for k in (1, 3, 5)}
    return {**at_least, "instances": len(o), "answerable": len(ans),
            "hidden_rate": round(float(ans["hidden"].mean()), 4) if len(ans) else np.nan,
            "miss_rate": round(float(ans["miss"].mean()), 4) if len(ans) else np.nan,
            "false_show_rate": round(float(o.loc[~o["answerable"], "false_show"].mean()), 4) if (~o["answerable"]).any() else np.nan,
            "precision_judged": round(float(o["n_shown_relevant"].sum() / judged), 4) if judged else np.nan,
            "precision_pessimistic": round(float(o["n_shown_relevant"].sum() / o["n_shown"].sum()), 4) if o["n_shown"].sum() else np.nan,
            "judged_share_of_shown": round(float(judged / o["n_shown"].sum()), 4) if o["n_shown"].sum() else np.nan,
            "mean_shown": round(float(o["n_shown"].mean()), 2),
            "shown_ge_10": round(float((o["n_shown"] >= 10).mean()), 4)}


__all__ = ["BINARY", "FEATURE_SETS", "add_features", "calibration_metrics", "fit", "instance_outcomes", "predict",
           "summarize_outcomes"]
