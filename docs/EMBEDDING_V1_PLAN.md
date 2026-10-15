# 임베딩 v1 확정 계획 — 후보 수집 → 일괄 판정 → 선택 → 검색 파이프라인 (2026-10-15)

회의·인수인계용 요약 문서. 규칙의 근거는 `docs/EVALUATION_POLICY.md`(평가·판정 공식 규칙), 서비스 적용 전체 그림은
`docs/SERVICE_READINESS.md`.

## 0. 한 장 요약

- **지금 단계는 "임베딩 단계(관련성 판단)" 평가다.** 검색·추천 시스템은 단계별로 개발·평가한 뒤 붙여서 전체를 검증하는 것이 업계 표준이다
  (후보 생성/순위 분리: Covington et al. RecSys 2016, 임베딩 상품 검색: Nigam et al. KDD 2019). 위치·거리 정렬은 뒤 단계의 일이다.
- **임베딩은 이번 일괄 판정 1회로 v1을 고정한다.** 현재 벤치마크는 천장 근처(판정 문서만 nDCG 0.95~0.96)이고, 남은 차이(0.01)는 val 124개로
  구분이 안 된다(필요 쿼리 약 515개). 더 튜닝해도 개선인지 잡음인지 판별할 수 없다.
- **팀원들이 학습한 bge-m3·Snowflake Arctic 최고 run과 kse14, 하이브리드·reranker 구성을 한 번에 판정 후보로 모아** 보충 판정 → val로 하나 선택 →
  test 1회.
- 그 다음 **검색 파이프라인(위치 필터·정렬, 하이브리드, reranker 여부, 벡터 DB/ANN 색인)을 구현**하고, 실제 쿼리+위치로 전체 성능을 잰다.
  부족하면 그때 실제 쿼리 기반 데이터로 재학습한다(현재 val에 맞추는 학습은 하지 않음).

## 1. 현재 상태 (val 124개 쿼리, 오타 쿼리 비활성 후)

| 구성 | 공식 nDCG@10 | 판정 문서만 nDCG@10 | Judged@10 | 1위 정답률 | bad@3 |
|---|---|---|---|---|---|
| Qwen3-Embedding-0.6B zero-shot | 0.920 | 0.920 | 1.000 | 0.903 | 21/124 |
| **kse14** (기준선) | 0.948 | 0.952 | 0.995 | 0.952 | 12/124 |
| kse14 + BM25 하이브리드(RRF) | 0.943 | 0.960 | 0.977 | 0.976 | 9/124 |
| kse14 + 하이브리드 + Qwen3-Reranker | (판정 후) | 0.963 | 0.920 | (판정 후) | (판정 후) |
| kse14 + Qwen3-Reranker | (판정 후) | 0.959 | 0.817 | (판정 후) | (판정 후) |
| kse14 + 하이브리드 + bge-reranker | (판정 후) | 0.958 | 0.929 | (판정 후) | (판정 후) |

- kse14 = `qwen3_embedding_0_6b_ft_kse14_20261014_0440`: LoRA rank 16, GIST loss, lr 1e-4, batch 32, **2 epoch**, 학습 쿼리 215개(6,650행),
  T4 fp16, 오타 증강 끔. 모델은 `models/`(git 제외), 기록은 `results/finetune_runs/`.
- reranker 구성은 판정 안 된 문서를 위로 올려 공식 점수·bad@3이 낮게 나온다(Judged@10 0.82~0.93) → 일괄 판정 뒤에 비교한다.
- 같은 설정도 다시 돌리면 nDCG@10이 ±0.005 흔들린다(kse1·kse13·kse14).

## 2. 전체 진행 순서와 통과 기준

| 단계 | 할 일 | 통과 기준 / 산출물 |
|---|---|---|
| ① 후보 수집 | kse14, 팀원 bge-m3·Arctic 최고 run, 하이브리드·reranker 구성의 **val+test run** 수집 | `configs/benchmark/judging_candidates.yaml` 등록 |
| ② 일괄 판정 1회 | 후보 상위 10개 중 판정 안 된 (쿼리, 가맹점)만 A·B 판정 → 조정 → qrels 갱신 | val·test Judged@10 ≥ 0.95(모든 후보) |
| ③ 임베딩 v1 선택 | val 공식 지표로 1개 선택, **test는 그 1개만 1회** 채점 | 선택 근거·test 결과 보고, v1 고정 |
| ④ 검색 파이프라인 | 위치 필터·정렬(거리, 필요시 인지도), 하이브리드 결합, reranker 여부(지연 예산), **벡터 DB/ANN 색인**, BM25 폴백 | ANN recall(exact 대비), 지연 p95 측정 |
| ⑤ 전체 성능 측정 | 실제 쿼리(로그·파일럿) + 검색 위치. 반경 안 가맹점은 수백 개라 **전수 판정** 가능 → 정밀도·재현율. 현행 검색과 side-by-side | 쿼리 500개 이상에서 bad@3 상한 ≤ 목표, 현행 대비 우위 |
| ⑥ 부족하면 재학습 | ⑤의 실패 **유형**에 맞춰 실제 쿼리 기반 데이터·코퍼스 기반 합성 데이터로 v2 학습 | ⑤ 지표로 비교 |
| ⑦ 서비스 연결 | 운영 색인·모니터링·폴백 → shadow → interleaving/A/B → 단계적 확대 | 온라인 지표(클릭률, 결과 없음 비율, 재검색률) |

벡터 DB는 ⑦이 아니라 ④에 넣는다 — ANN 색인은 exact 검색과 결과가 조금 달라서, ⑤의 전체 성능은 ANN을 붙인 상태로 재야 한다.

## 3. 후보 모으기 (①)

### 3-1. 누가 무엇을
| 후보 | 담당 | 방법 |
|---|---|---|
| kse14 | 데이터 담당 | 노트북 15번 `POOL_RUN_FINETUNED = ["qwen3_embedding_0_6b_ft_kse14_20261014_0440"]` |
| bge-m3 / Snowflake Arctic 학습 run | 각 담당 팀원 | 자기 run 중 **val 기준 1~2개**를 골라(아래 기준) KEEP 표시 → 노트북 15번 `POOL_RUN_FINETUNED`에 TAG |
| 하이브리드·reranker | 데이터 담당(로컬) | kse14 val+test run이 생긴 뒤 `eval_retrieval_stack.py --split test`, reranker 점수는 Colab |

노트북 15번은 val+test 상위 100개 검색 결과를 **채점하지 않고** Drive `runs/pooling_runs/<TAG>.csv`로 저장한다(test 점수를 미리 보지 않음).

### 3-2. 팀원 run 고르는 기준(판정 없이)
- 노트북 리더보드의 서비스 지표 **nDCG@10(판정만)** 이 가장 높은 run, 비슷하면 bad@3·1위 정답률이 좋은 run.
- Judged@10이 0.95 미만이면 공식 nDCG가 낮게 나온 것이므로 공식 nDCG로 탈락시키지 않는다.
- 어떤 학습 데이터로 학습했는지(manifest `training_data.sha256`)를 NOTE에 남긴다. 오타 비활성 전 데이터(237 쿼리)로 학습한 run도 후보가 될 수 있다
  (학습은 train 업종만 쓰므로 val/test 누설은 없다). 평가는 현재 qrels 기준이어야 하므로 노트북 16번 재채점 후 리더보드를 본다.

### 3-3. 등록
`configs/benchmark/judging_candidates.yaml`의 `candidates`에 name·note·val·test 경로를 적는다. 노트북 15번 결과처럼 val+test가 한 파일이면
val·test에 같은 경로를 적는다. 후보는 넉넉히 넣어도 된다 — 이미 판정된 쌍은 다시 판정하지 않아 비용은 새로 나온 문서만큼만 는다.

## 4. 일괄 판정 (②) — 명령과 순서

```bash
# 1) 후보 검증 + depth별 판정 건수(아무것도 쓰지 않음)
python scripts/collect_judging_candidates.py
# 2) depth(기본 10)를 확인하고 시트 생성 → benchmark/storesearch_ko_v1/annotations/final_v1/annotation_A.csv, annotation_B.csv
python scripts/collect_judging_candidates.py --make --reason "임베딩 v1 후보 일괄 판정"
# 3) A·B가 서로 모르게 판정 → annotations/final_v1/completed/annotation_A_completed.csv, annotation_B_completed.csv
python scripts/16_supplemental_round.py merge --round final_v1     # 불일치 → analysis/adjudication_needed_only.csv 조정 → 다시 merge
python scripts/11_build_qrels.py
python scripts/12_validate_benchmark.py --stage final
python scripts/rescore_evaluations.py                                # 저장소의 기존 평가 다시 채점
python scripts/pack_for_colab.py                                     # Drive data/ 교체 → 노트북 16번(Drive 평가 다시 채점)
```

- 판정 시트에는 시스템 이름·순위가 없고 행 순서가 섞여 있다(판정자 편향 방지). 판정 기준은 기존 가이드라인 그대로.
- 규모 예상: val만 kse14 계열 4개 후보 depth 10 → 284쌍(2026-10-15 시험 계산). 다른 계열 모델(bge-m3·Arctic)과 test가 더해지면 늘어난다 —
  `collect_judging_candidates.py` 표로 확정한다.
- 판정은 이 라운드 한 번. 끝난 뒤 판정을 고치거나 val을 보며 다시 판정하지 않는다.

## 5. 선택 규칙 (③)

1. 판정 뒤 val 공식 지표로 비교: nDCG@10(95% CI), Judged@10, bad@3, 1위 정답률, 기준(kse14) 대비 Δ·p.
2. "더 낫다"는 Δ ≥ 0.03이고 p < 0.05일 때만. 그보다 작은 차이는 **같은 수준**으로 본다.
3. 같은 수준이면 **단순하고 싼 구성**을 고른다: 임베딩 단독 < +하이브리드 < +reranker(지연·GPU 비용). 서비스 지표(bad@3, 1위 정답률)가
   분명히 나은 경우만 더 복잡한 구성을 택한다.
4. 고른 구성 1개만 test 1회 채점해 보고한다. test를 보고 다시 고르지 않는다.

## 6. main 브랜치와 달라진 점

두 브랜치가 아직 main에 머지되지 않았다: `feature/qwen3-embedding-finetuning` → 그 위에 `feature/hybrid-rerank`.

| 구분 | 변경 | 이유 |
|---|---|---|
| 벤치마크 데이터 | 오타 쿼리 49개 비활성(`configs/benchmark/inactive_queries_v1.yaml`, train 22/val 12/test 15). active 499개(train 215/val 124/test 160). qrels에서 그 판정 6,018행 제외(판정 기록은 보존) | 오타는 검색 앞단 철자 교정의 일 — 기본 성능 확정 뒤 다룸(팀 결정 2026-10-14) |
| 학습 데이터 | `train_pairs.jsonl` 237 → 215 쿼리(sha `ec3a9b61`) | 위와 같음 |
| 기준선 | kse13(구 데이터) → **kse14**(새 데이터) | 학습·평가 조건을 맞춤 |
| 노트북 | 오타 증강 옵션(`typo_variants_per_query`, 기본 0 — 효과 없어 끔), 리더보드 서비스 지표(bad@3, 1위 정답률, **nDCG@10(판정만)**) | 서비스 체감 지표, 판정 없이 탐색 |
| 평가 도구 | `rescore_evaluations.py`(qrels 변경 후 재채점, 비활성 쿼리 행 정리), `import_colab_results.py`(예전 qrels 평가·비활성 쿼리 자동 처리) | 데이터 변경 뒤 기록 일관성 |
| 검색 구성 비교 | `eval_retrieval_stack.py`(BM25 하이브리드 RRF, bge/Qwen3 reranker, test run 생성), `colab/rerank_scores.ipynb`(GPU 채점) | 학습 없이 시스템 구성 효과 측정 |
| 일괄 판정 | `configs/benchmark/judging_candidates.yaml`, `scripts/collect_judging_candidates.py` | 중간 판정 없이 후보를 모아 한 번에 |
| 문서 | `EVALUATION_POLICY.md`(공식 규칙), `SERVICE_READINESS.md`, 이 문서 | 회의·인수인계 |
| 결과 | `results/experiments.csv`에 kse13·kse14, `results/stack_eval/val/` | |

머지 순서: 두 브랜치를 하나의 PR로 올리거나(`feature/hybrid-rerank` → main, 앞 브랜치 커밋 포함) 순서대로 두 PR. 머지 후 Drive `data/`는
`pack_for_colab.py` 결과로 교체돼 있어야 한다(오타 비활성 반영).

## 7. 결정 기록

| 날짜 | 결정 | 근거 |
|---|---|---|
| 2026-10-13 | 오타 증강 학습 채택 안 함 | kse13 대비 Δ +0.001(p=0.70), 오타 쿼리 bad@3 그대로 |
| 2026-10-14 | 오타 쿼리 49개 비활성 | 철자 교정 단계로 미룸, val 오타 12개로는 판단 불가 |
| 2026-10-14 | val 실패 쿼리에 맞춘 데이터 추가 안 함 | val 과적합(Dwork et al. 2015), 효과가 측정 잡음 수준 |
| 2026-10-15 | 평가·판정 공식 규칙 채택, 일괄 판정 | `EVALUATION_POLICY.md` |
| 2026-10-15 | 임베딩은 일괄 판정 1회로 v1 고정, 위치는 파이프라인 단계에서 | 단계별 개발·평가가 업계 표준, 현재 벤치마크로 0.01 차이 측정 불가 |
