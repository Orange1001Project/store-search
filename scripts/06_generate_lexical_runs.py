from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer

from store_search_ai.pipeline.common import load_active_queries, load_config

TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def normalize_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split())


def tokenize(value: object) -> list[str]:
    return TOKEN_RE.findall(normalize_text(value).casefold())


def top_indices(scores: np.ndarray, k: int) -> np.ndarray:
    scores = np.asarray(scores, dtype=float)
    n = len(scores)
    if n == 0:
        return np.array([], dtype=int)
    k = min(k, n)
    if k == n:
        return np.argsort(-scores)
    idx = np.argpartition(-scores, k - 1)[:k]
    return idx[np.argsort(-scores[idx])]


def save_run(
    system: str,
    queries: pd.DataFrame,
    corpus: pd.DataFrame,
    score_fn,
    top_k: int,
    output_dir: Path,
) -> dict:
    """
    Retrieval run 저장.

    중요:
    score <= 0인 문서는 retrieval 결과로 기록하지 않는다.

    이유:
    lexical overlap이 전혀 없는 query에서는
    BM25/TF-IDF score가 전체 0이 될 수 있다.

    이 상태에서 강제로 Top-K를 만들면
    임의 document가 retrieval result처럼 들어가
    annotation pool을 오염시킨다.

    Random negative는 별도의 pooling channel에서
    명시적으로 sampling한다.
    """

    rows = []

    query_with_results = 0
    query_without_results = 0
    result_counts = []

    for q in queries.itertuples(
        index=False
    ):

        scores = np.asarray(
            score_fn(q.query),
            dtype=float,
        )

        # --------------------------------------------------
        # 실제 retrieval signal이 존재하는 document만 사용
        # --------------------------------------------------

        valid_indices = np.flatnonzero(
            np.isfinite(scores)
            & (scores > 0)
        )

        if len(valid_indices) == 0:

            query_without_results += 1
            result_counts.append(0)

            continue

        ranked_indices = valid_indices[
            np.argsort(
                -scores[
                    valid_indices
                ]
            )
        ]

        ranked_indices = (
            ranked_indices[
                :top_k
            ]
        )

        query_with_results += 1

        result_counts.append(
            len(
                ranked_indices
            )
        )

        for rank, idx in enumerate(
            ranked_indices,
            start=1,
        ):

            rows.append(
                {
                    "query_id":
                        q.query_id,

                    "doc_id":
                        corpus.iloc[
                            idx
                        ]["doc_id"],

                    "rank":
                        rank,

                    "score":
                        float(
                            scores[
                                idx
                            ]
                        ),

                    "system":
                        system,
                }
            )

    out = pd.DataFrame(
        rows,
        columns=[
            "query_id",
            "doc_id",
            "rank",
            "score",
            "system",
        ],
    )

    csv_path = (
        output_dir
        / f"{system}.csv"
    )

    out.to_csv(
        csv_path,
        index=False,
        encoding="utf-8-sig",
    )

    trec_path = (
        output_dir
        / f"{system}.trec"
    )

    with trec_path.open(
        "w",
        encoding="utf-8",
    ) as f:

        for r in out.itertuples(
            index=False
        ):

            f.write(
                f"{r.query_id} "
                f"Q0 "
                f"{r.doc_id} "
                f"{r.rank} "
                f"{r.score:.12f} "
                f"{system}\n"
            )

    stats = {

        "system":
            system,

        "queries":
            int(
                len(
                    queries
                )
            ),

        "queries_with_results":
            int(
                query_with_results
            ),

        "queries_without_results":
            int(
                query_without_results
            ),

        "run_rows":
            int(
                len(
                    out
                )
            ),

        "mean_results_per_query":
            float(
                np.mean(
                    result_counts
                )
            )
            if result_counts
            else 0.0,

        "max_results_per_query":
            int(
                max(
                    result_counts
                )
            )
            if result_counts
            else 0,

        "zero_or_negative_score_rows":
            int(
                (
                    out["score"] <= 0
                ).sum()
            )
            if len(out)
            else 0,
    }

    print()
    print(
        f"[RUN] {system}"
    )
    print(
        json.dumps(
            stats,
            ensure_ascii=False,
            indent=2,
        )
    )

    return stats

# def save_run(system: str, queries: pd.DataFrame, corpus: pd.DataFrame, score_fn, top_k: int, output_dir: Path) -> None:
#     rows = []
#     for q in queries.itertuples(index=False):
#         scores = np.asarray(score_fn(q.query), dtype=float)
#         idxs = top_indices(scores, top_k)
#         for rank, idx in enumerate(idxs, start=1):
#             rows.append(
#                 {
#                     "query_id": q.query_id,
#                     "doc_id": corpus.iloc[idx]["doc_id"],
#                     "rank": rank,
#                     "score": float(scores[idx]),
#                     "system": system,
#                 }
#             )

#     out = pd.DataFrame(rows)
#     out.to_csv(output_dir / f"{system}.csv", index=False, encoding="utf-8-sig")
#     with (output_dir / f"{system}.trec").open("w", encoding="utf-8") as f:
#         for r in out.itertuples(index=False):
#             f.write(f"{r.query_id} Q0 {r.doc_id} {r.rank} {r.score:.12f} {system}\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    corpus = pd.read_parquet(config["corpus_path"])
    benchmark_dir = Path(config["benchmark_dir"])
    queries = load_active_queries(benchmark_dir)
    run_depth = int(config["pooling"]["run_depth"])

    output_dir = benchmark_dir / "runs" / "pooling"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Pool discovery only. Production model T1/T2/T3 evaluation remains separate.
    docs = (
        corpus["store_name"].fillna("").map(normalize_text)
        + " "
        + corpus["item_text"].fillna("").map(normalize_text)
    ).str.strip()

    print("[INFO] fitting char TF-IDF...")
    char_vec = TfidfVectorizer(
        analyzer="char_wb", ngram_range=(2, 5), min_df=1,
        sublinear_tf=True, max_features=150000,
    )
    char_mat = char_vec.fit_transform(docs)
    def char_scores(query: str) -> np.ndarray:
        return (char_vec.transform([query]) @ char_mat.T).toarray()[0]

    print("[INFO] fitting word TF-IDF...")
    word_vec = TfidfVectorizer(
        analyzer="word", ngram_range=(1, 2),
        token_pattern=r"(?u)\b\w+\b", min_df=1, sublinear_tf=True,
    )
    word_mat = word_vec.fit_transform(docs)
    def word_scores(query: str) -> np.ndarray:
        return (word_vec.transform([query]) @ word_mat.T).toarray()[0]

    print("[INFO] fitting BM25 regex-token baseline...")
    bm25 = BM25Okapi([tokenize(x) for x in docs.tolist()])
    def bm25_scores(query: str) -> np.ndarray:
        return np.asarray(bm25.get_scores(tokenize(query)), dtype=float)

    # save_run("char_tfidf_v1", queries, corpus, char_scores, run_depth, output_dir)
    # save_run("word_tfidf_v1", queries, corpus, word_scores, run_depth, output_dir)
    # save_run("bm25_regex_v1", queries, corpus, bm25_scores, run_depth, output_dir)

    run_stats = []

    run_stats.append(
        save_run(
            "char_tfidf_v1",
            queries,
            corpus,
            char_scores,
            run_depth,
            output_dir,
        )
    )

    run_stats.append(
        save_run(
            "word_tfidf_v1",
            queries,
            corpus,
            word_scores,
            run_depth,
            output_dir,
        )
    )

    run_stats.append(
        save_run(
            "bm25_regex_v1",
            queries,
            corpus,
            bm25_scores,
            run_depth,
            output_dir,
        )
    )

    manifest = {
        "run_depth": run_depth,
        "systems": ["char_tfidf_v1", "word_tfidf_v1", "bm25_regex_v1"],
        "pool_text_fields": ["store_name", "item_text"],
        "run_stats": run_stats,
        "important": "Pooling runs use query text only; positive/boundary terms never alter retrieval scores.",
    }
    (output_dir / "lexical_run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("========== LEXICAL POOLING RUNS COMPLETE ==========")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
