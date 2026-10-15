# 평가·판정 운영 원칙 (공식, 2026-10-15 채택)

모델·검색 구성을 비교할 때 **언제 판정하고, 무엇으로 고르고, 어떻게 보고하는지** 정한 문서다. 판정 절차 자체(가이드라인, A/B 이중 판정,
조정)는 `benchmark/storesearch_ko_v1/annotation_guideline.md`와 `docs/PIPELINE.md` 4~6절을 따른다.

## 1. 원칙 — 시스템이 낸 결과를 사람이 판정해서 지표를 만든다

정답(qrels)은 미리 전부 만들 수 없다(21만 매장 × 쿼리). 그래서 **비교할 시스템들의 상위 결과를 모아(pool) 사람이 판정하고, 그 판정으로
모든 시스템을 채점한다.** TREC(1992~), TREC Deep Learning Track의 표준 방식이고, 서비스의 사람 평가(검색 품질 평가자, side-by-side)도
"실험 시스템이 실제로 낸 결과를 판정한다"는 점에서 같다. 순환 논리가 되지 않으려면 아래를 지킨다.

| 조건 | 이유 | 이 저장소에서 |
|---|---|---|
| 판정자는 어느 시스템·몇 위 결과인지 모른다 | 알면 새 시스템에 후하게 매기는 편향 | 판정 시트에 시스템·순위 없음, 행 순서 무작위(`16 make-runs`) |
| 비교하는 시스템 **전부**의 상위 결과를 같은 라운드에서 판정 | 한쪽만 판정하면 그쪽만 판정 누락을 벗어나 유리 | 일괄 판정(3절) |
| 판정은 (쿼리, 문서) 단위로 고정, 순위·시스템과 무관 | 같은 문서는 어느 시스템이 가져와도 같은 점수 | 기존 판정은 바꾸지 않고 새 쌍만 추가 |
| 판정 → 튜닝 → 판정을 같은 쿼리로 반복하지 않는다 | val을 외우게 됨(adaptive overfitting) | 일괄 판정은 결정 주기마다 한 번 |
| test는 판정을 먼저 끝내고 점수는 마지막에 한 번 | 점수를 보고 판정·구성을 바꾸면 test가 오염 | test run은 채점 없이 만든다 |

## 2. 탐색 단계 — 판정하지 않고 고른다

새 모델·구성이 나올 때마다 판정하지 않는다. 대신 아래 지표를 같이 보고 **후보를 고르기만** 한다.

| 지표 | 어디서 | 쓰는 법 |
|---|---|---|
| 공식 nDCG@10 (+95% CI, 기준 대비 Δ·p) | 노트북 리더보드, `eval_retrieval_stack.py` | Judged@10 ≥ 0.95일 때만 그대로 믿는다 |
| **Judged@10** | 같음 | 0.95 미만이면 판정 누락이 점수를 깎고 있다 → 공식 nDCG로 "나빠졌다"고 하지 않는다 |
| **nDCG@10(판정만)** (condensed nDCG, Sakai 2007) | 노트북 서비스 지표, `eval_retrieval_stack.py` | 판정된 문서만 남겨 매긴 값. 판정 누락에 강해 탐색의 주 지표 |
| bad@3, top1_ok | 같음 | 서비스 체감(상위 3개 오답 쿼리 비율, 목표 ≤ 0.05). 판정 없음도 오답으로 세므로 보수적 |

**후보 등록 기준**: 기준 모델 대비 nDCG@10(판정만)이 떨어지지 않고(−0.005 이내) bad@3·top1_ok 중 하나 이상이 좋아진 구성,
또는 성격이 다른 계열(새 모델 계열·새 검색 구성)이라 판정 없이는 비교가 안 되는 구성. 등록은
`configs/benchmark/judging_candidates.yaml`에 적기만 한다.

val 실패 쿼리를 보고 그 쿼리에 맞춘 데이터·규칙을 만들지 않는다. 실패는 **유형**을 파악하는 데만 쓰고, 해결책은 특정 쿼리와 무관한
절차(코퍼스 전체 기반 데이터 생성 등)로 만든다.

## 3. 일괄 판정 — 후보가 모이면 한 번에

결정을 내려야 할 때(최종 후보를 고를 때, test를 보기 전) **등록된 후보 전부를 한 라운드에서** 판정한다.

1. 후보마다 val·test run을 만든다(test는 채점하지 않음).
   - dense 모델: 노트북 15번(`runs/pooling_runs/<이름>.csv`, val+test 상위 100)
   - 하이브리드·reranker: `python scripts/eval_retrieval_stack.py --split test --dense-dir <pooling_runs> --dense <이름> ...`
     (reranker 점수는 `--export-pairs` → `colab/rerank_scores.ipynb`)
2. `configs/benchmark/judging_candidates.yaml`에 등록(name, note, val, test).
3. `python scripts/collect_judging_candidates.py` — 후보 검증 + depth별 판정 건수 표(아무것도 쓰지 않음).
4. depth를 정해(기본 10) `python scripts/collect_judging_candidates.py --make --reason "..."` → `annotations/<round>/` A·B 시트.
5. A·B 독립 판정 → `16_supplemental_round.py merge` → 조정 → `11_build_qrels.py` → `12_validate_benchmark.py --stage final`
   → `rescore_evaluations.py`(기존 평가 다시 채점) → 노트북 16번(Drive 평가 다시 채점).
6. val 공식 지표로 최종 구성 **하나**를 고르고, 그 구성만 test를 한 번 채점해 보고한다.

이미 pool에 있는 (쿼리, 문서)는 다시 판정하지 않으므로 후보를 넉넉히 넣어도 비용은 "새로 나온 문서"만큼만 는다. 예: val만, kse14 계열 후보
4개 depth 10 → 284쌍(2026-10-15 dry-run).

## 4. 보고 형식

비교 결과는 항상 아래를 같이 적는다: 쿼리 수, 공식 nDCG@10(95% CI), Judged@10, nDCG@10(판정만), bad@3(개수/전체), top1_ok,
기준 대비 Δ·p(paired permutation)·wins/ties/losses. Δ < 0.03이거나 p ≥ 0.05면 "개선"이라 하지 않는다. 같은 설정도 다시 돌리면
nDCG@10이 ±0.005 정도 흔들린다(kse1·kse13, 2026-10) — 차이가 그 정도면 seed를 바꿔 다시 확인한다.

## 근거

- Voorhees & Harman (2005), *TREC: Experiment and Evaluation in Information Retrieval* — pooling과 재사용 가능한 판정.
- Zobel (1998), *How reliable are the results of large-scale IR experiments?* — pool에 참여하지 않은 시스템이 불리해지는 문제.
- Buckley & Voorhees (2004), *Retrieval evaluation with incomplete information* (bpref); Sakai (2007), *Alternatives to bpref*
  (condensed list) — 판정 누락에 강한 지표.
- Craswell et al. (2020~), *Overview of the TREC Deep Learning Track* — 참가 run 기반 pooling + 사람 판정.
- Dwork et al. (2015), *The reusable holdout*, Science — 평가 데이터를 반복해서 보며 맞추면 생기는 과적합.
- Upadhyay et al. (2024), *UMBRELA* / TREC RAG 2024 — 판정 누락분을 LLM이 판정하고 사람 판정과의 일치도로 검증(비용 절감 선택지).
