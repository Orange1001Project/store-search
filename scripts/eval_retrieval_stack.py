"""검색 구성 비교(학습 없음): dense run + char BM25 하이브리드(RRF) + cross-encoder reranker를 val에서 공식 evaluator로 잰다.

    dense run          results/model_eval/<tag>/run_t1_minimal_<split>.csv (이미 있는 것 — Colab 평가 결과)
    BM25               char n-gram BM25(06번 pooling의 char_bm25_v1과 같은 텍스트·채점기), 상위 100
    하이브리드         RRF(Cormack et al. 2009): score = Σ 1 / (k + rank), k=60, 상위 100
    reranker           각 run의 상위 --rerank-depth개를 cross-encoder 점수로 다시 정렬(나머지는 뒤에 그대로)

결과는 results/stack_eval/<split>/ 에 run 파일과 summary.csv로 남긴다(공식 실험 기록표와는 별도 — 탐색용).
reranker는 판정되지 않은 문서를 위로 올릴 수 있어(판정 없음 = 오답으로 계산) Judged@10과, 판정된 문서만 남겨 매긴
condensed nDCG@10(Sakai 2007)도 같이 출력한다. GPU가 없어도 돈다(CPU, 쿼리 124개 × 50개 기준 모델당 몇 분).

사용법:
    python scripts/eval_retrieval_stack.py --dense qwen3_embedding_0_6b qwen3_embedding_0_6b_ft_kse14_20261014_0440 \
        --rerankers BAAI/bge-reranker-v2-m3

reranker를 Colab GPU에서 채점할 때(Qwen3-Reranker는 CPU로 1시간 이상):
    1) 같은 명령에 --export-pairs → results/stack_eval/val/rerank_pairs.csv를 Drive store-search-ai/stack_eval/에 올림
    2) colab/rerank_scores.ipynb 실행 → rerank_scores_<모델>.csv를 results/stack_eval/val/에 넣음
    3) 같은 명령을 --rerankers <모델>로 다시 실행 → 캐시 점수로 비교만 한다(다시 채점하지 않음)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from store_search_ai.evaluation.evaluator import (
    build_evaluation_report,
    calculate_metrics,
    load_qrels,
    load_run,
)
from store_search_ai.pipeline.common import load_active_queries, load_config
from store_search_ai.retrieval.lexical import (
    build_pool_document_texts,
    fit_bm25_scorer,
    retrieve_run,
)

RUN_COLUMNS = ["query_id", "doc_id", "rank", "score", "system"]


def rrf_fuse(runs: list[pd.DataFrame], system: str, k: int = 60, top_k: int = 100) -> pd.DataFrame:
    """Reciprocal Rank Fusion. 같은 점수면 doc_id 순으로(결과가 실행마다 같도록)."""

    fused = pd.concat([r.assign(rrf=1.0 / (k + r["rank"])) for r in runs])
    fused = fused.groupby(["query_id", "doc_id"], as_index=False)["rrf"].sum()
    fused = fused.sort_values(["query_id", "rrf", "doc_id"], ascending=[True, False, True])
    fused["rank"] = fused.groupby("query_id").cumcount() + 1
    fused = fused[fused["rank"] <= top_k].rename(columns={"rrf": "score"}).assign(system=system)
    return fused[RUN_COLUMNS].reset_index(drop=True)


def rerank(run: pd.DataFrame, scores: dict[tuple[str, str], float], depth: int, system: str) -> pd.DataFrame:
    """상위 depth개를 reranker 점수로 다시 정렬하고, 그 아래는 원래 순서대로 뒤에 붙인다."""

    out = []
    for qid, group in run.sort_values(["query_id", "rank"]).groupby("query_id", sort=True):
        head, tail = group.iloc[:depth], group.iloc[depth:]
        head = head.assign(new=[scores[(qid, d)] for d in head["doc_id"]]).sort_values(["new", "rank"], ascending=[False, True])
        ordered = pd.concat([head.drop(columns="new"), tail])
        n = len(ordered)
        out.append(ordered.assign(rank=np.arange(1, n + 1), score=np.arange(n, 0, -1, dtype=float), system=system))
    return pd.concat(out)[RUN_COLUMNS].reset_index(drop=True)


def load_reranker(name: str):
    """(query, doc) 쌍 목록 → 점수 배열 함수. bge 계열은 CrossEncoder, Qwen3-Reranker는 공식 yes/no 방식."""

    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    if "qwen3-reranker" not in name.lower():
        from sentence_transformers import CrossEncoder

        model = CrossEncoder(name, max_length=256, device=device)
        return lambda pairs: model.predict(pairs, batch_size=64, show_progress_bar=True)

    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(name, padding_side="left")
    model = AutoModelForCausalLM.from_pretrained(name, dtype=torch.float32).to(device).eval()
    yes, no = tok.convert_tokens_to_ids("yes"), tok.convert_tokens_to_ids("no")
    prefix = ("<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct "
              "provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n")
    suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
    instruct = "Given a Korean local-store search query, judge whether the store satisfies the user's shopping, dining, or service intent"

    def score(pairs):
        # 마지막 토큰의 yes/no 두 개 logit만 필요하다 — 출력층(어휘 15만 개)을 전체 토큰에 돌리면 계산이 수백 배가 되므로
        # 마지막 hidden state에 yes/no 두 행만 곱한다(왼쪽 padding이라 마지막 위치가 곧 각 문장의 끝).
        head = model.lm_head.weight[[no, yes]]
        out = []
        for i in range(0, len(pairs), 32):
            texts = [f"{prefix}<Instruct>: {instruct}\n<Query>: {q}\n<Document>: {d}{suffix}" for q, d in pairs[i:i + 32]]
            batch = tok(texts, padding=True, truncation=True, max_length=512, return_tensors="pt").to(device)
            with torch.no_grad():
                hidden = model.model(**batch).last_hidden_state[:, -1]
                logits = hidden @ head.T
            out.extend(torch.log_softmax(logits, dim=-1)[:, 1].exp().cpu().tolist())
            if (i // 32) % 20 == 0:
                print(f"  {min(i + 32, len(pairs))}/{len(pairs)}", flush=True)
        return np.asarray(out)

    return score


def service_metrics(run: pd.DataFrame, rel: dict, query_types: pd.Series) -> dict:
    top = run[run["rank"] <= 3].sort_values(["query_id", "rank"])
    top = top.assign(g=[rel.get((q, d), -1) for q, d in zip(top["query_id"], top["doc_id"])])
    per = top.groupby("query_id").agg(bad=("g", lambda s: bool((s <= 1).any())), top1=("g", lambda s: bool(s.iloc[0] >= 2)))
    per = per.join(query_types)
    out = {"bad@3": per["bad"].mean(), "bad@3_n": int(per["bad"].sum()), "top1_ok": per["top1"].mean()}
    out.update({f"bad@3 {t.split()[0]}": v for t, v in per.groupby("query_type")["bad"].mean().items()})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/benchmark/storesearch_ko_v1.yaml")
    parser.add_argument("--split", default="val", choices=["val"], help="test는 최종 구성을 정한 뒤 별도로")
    parser.add_argument("--dense", nargs="+", required=True, help="results/model_eval/ 아래 dense run 폴더 이름")
    parser.add_argument("--rerankers", nargs="*", default=["BAAI/bge-reranker-v2-m3"])
    parser.add_argument("--rerank-depth", type=int, default=50)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--baseline", default=None, help="Δ·p를 잴 기준 run 이름(기본: --dense 마지막)")
    parser.add_argument("--export-pairs", action="store_true",
                        help="reranker가 채점할 (쿼리, 문서) 쌍만 rerank_pairs.csv로 내보내고 끝(Colab GPU에서 채점할 때)")
    args = parser.parse_args()

    config = load_config(args.config)
    benchmark_dir = Path(config["benchmark_dir"])
    out_dir = Path("results/stack_eval") / args.split
    out_dir.mkdir(parents=True, exist_ok=True)
    qrels_path = benchmark_dir / f"qrels_{args.split}.trec"
    queries = load_active_queries(benchmark_dir)
    queries = queries[queries["split"] == args.split].reset_index(drop=True)
    qids = set(queries["query_id"].astype(str))
    corpus = pd.read_parquet(config["corpus_path"])
    doc_text = corpus.set_index("doc_id")["search_text_t1_minimal"].fillna("").astype(str)
    rel = {(q.query_id, q.doc_id): q.relevance for q in load_qrels(qrels_path)}
    judged = set(rel)

    runs: dict[str, pd.DataFrame] = {}
    for tag in args.dense:
        run = pd.read_csv(Path("results/model_eval") / tag / f"run_t1_minimal_{args.split}.csv", encoding="utf-8-sig")
        runs[tag] = run[run["query_id"].astype(str).isin(qids)][RUN_COLUMNS]

    bm25_path = out_dir / "char_bm25_v1.csv"
    if bm25_path.exists():
        runs["char_bm25_v1"] = pd.read_csv(bm25_path, encoding="utf-8-sig")
    else:
        print("[BM25] 코퍼스 색인 중(몇 분)…")
        scorer = fit_bm25_scorer(build_pool_document_texts(corpus))
        runs["char_bm25_v1"], _ = retrieve_run("char_bm25_v1", queries, corpus, scorer, 100)
        runs["char_bm25_v1"].to_csv(bm25_path, index=False, encoding="utf-8-sig", lineterminator="\n")
    for tag in args.dense:
        runs[f"{tag}+bm25_rrf"] = rrf_fuse([runs[tag], runs["char_bm25_v1"]], f"{tag}+bm25_rrf", k=args.rrf_k)

    bases = [t for t in runs if t != "char_bm25_v1"]
    pairs = set()
    for t in bases:
        top = runs[t][runs[t]["rank"] <= args.rerank_depth]
        pairs |= set(zip(top["query_id"], top["doc_id"]))
    if args.export_pairs:
        text = dict(zip(queries["query_id"], queries["query"]))
        path = out_dir / "rerank_pairs.csv"
        pd.DataFrame([(q, d, text[q], doc_text[d]) for q, d in sorted(pairs)],
                     columns=["query_id", "doc_id", "query", "doc_text"]).to_csv(
            path, index=False, encoding="utf-8-sig", lineterminator="\n")
        print(f"[내보냄] {path} ({len(pairs)}쌍) — Drive store-search-ai/stack_eval/에 올리고 colab/rerank_scores.ipynb 실행")
        return
    for name in args.rerankers:
        short = name.split("/")[-1]
        cache_path = out_dir / f"rerank_scores_{short}.csv"
        cache = (pd.read_csv(cache_path, encoding="utf-8-sig").set_index(["query_id", "doc_id"])["score"].to_dict()
                 if cache_path.exists() else {})
        need = sorted(pairs - set(cache))
        if need:
            print(f"[rerank] {short}: 새로 채점할 쌍 {len(need)}개")
            text = dict(zip(queries["query_id"], queries["query"]))
            scores = load_reranker(name)([(text[q], doc_text[d]) for q, d in need])
            cache.update({k: float(s) for k, s in zip(need, scores)})
            pd.DataFrame([(q, d, s) for (q, d), s in cache.items()], columns=["query_id", "doc_id", "score"]).to_csv(
                cache_path, index=False, encoding="utf-8-sig", lineterminator="\n")
        for t in bases:
            runs[f"{t}+rerank_{short}"] = rerank(runs[t], cache, args.rerank_depth, f"{t}+rerank_{short}")

    baseline = args.baseline or args.dense[-1]
    base_path = out_dir / f"{baseline}.csv"
    rows = []
    for tag, run in runs.items():
        path = out_dir / f"{tag}.csv"
        run.to_csv(path, index=False, encoding="utf-8-sig", lineterminator="\n")
    for tag, run in runs.items():
        path = out_dir / f"{tag}.csv"
        report, _ = build_evaluation_report(qrels_path, path, tag, 10000, 20260831,
                                            None if tag == baseline else base_path, baseline)
        condensed = run[[(q, d) in judged for q, d in zip(run["query_id"], run["doc_id"])]]
        condensed = condensed.assign(rank=condensed.groupby("query_id").cumcount() + 1)
        cpath = out_dir / f"_condensed_{tag}.csv"
        condensed.to_csv(cpath, index=False, encoding="utf-8-sig", lineterminator="\n")
        cagg, _ = calculate_metrics(load_qrels(qrels_path), load_run(cpath))
        cpath.unlink()
        cmp = (report.get("comparison") or {}).get("metrics", {}).get("nDCG@10", {})
        rows.append({"run": tag, "nDCG@10": report["aggregate"]["nDCG@10"], "condensed nDCG@10": cagg["nDCG@10"],
                     "Judged@10": report["aggregate"]["Judged@10"], "MRR@100": report["aggregate"]["MRR@100"],
                     f"Δ vs {baseline[:24]}": cmp.get("delta_mean"), "p": cmp.get("paired_permutation_pvalue"),
                     **service_metrics(run, rel, queries.set_index("query_id")["query_type"])})
    table = pd.DataFrame(rows).sort_values("nDCG@10", ascending=False)
    table.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    (out_dir / "summary_config.json").write_text(json.dumps(vars(args), ensure_ascii=False, indent=2), encoding="utf-8")
    pd.set_option("display.width", 250)
    print(table.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
