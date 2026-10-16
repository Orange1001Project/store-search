# results/ — 실험 결과 기록

모델 가중치는 여기 두지 않는다(`models/`, git 제외 — `.gitignore`가 `results/` 아래 `*.safetensors`·`*.bin`도 막음).
Colab 결과는 손으로 복사하지 말고 `scripts/import_colab_results.py --drive-dir <내려받은 store-search-ai> --verify`로 가져온다
(`docs/TRAINING_TEAM.md` 9절).

| 경로 | 내용 | 만드는 곳 | git |
|---|---|---|---|
| `experiments.csv` | **실험 기록표** — 공식 평가 하나당 한 줄(모델, 누가, NOTE, 학습 데이터 sha, GPU, precision, 지표, 기준 대비 Δ·p, KEEP) | `import_colab_results.py`, 지표 갱신은 `rescore_evaluations.py` | 추적 |
| `model_eval/<run 이름>/run_t1_minimal_val.csv` | 공식 평가에 쓴 검색 결과(쿼리별 상위 100). 평가 json은 `artifacts/evaluation/storesearch_ko_v1/` | `import_colab_results.py` | 추적 |
| `finetune_runs/<TAG>/` | 학습 run 기록(`model_manifest.json`, `eval_config.yaml`, `notebook_code.py`) — 가중치 없이 어떤 설정·데이터·코드로 학습했는지 | `import_colab_results.py` | 추적 |
| `stack_eval/<split>/` | **검색 파이프라인 사전 탐색**(하이브리드·reranker, 학습 없음) — BM25 run·reranker 점수 캐시만 추적(Qwen3 기준 요약·하이브리드 run은 2026-10-16 삭제, ④에서 v1으로 다시 만든다) | `scripts/eval_retrieval_stack.py` | 일부 추적(다시 만들 수 있는 run 사본은 제외) |
| `judging_candidates/<round>/` | 일괄 판정 후보 run 모음(val+test, 시스템 이름 = 후보 name) | `scripts/collect_judging_candidates.py` | 판정 라운드 때 생성 |
| `model_comparison/<round>/` | 판정 라운드 뒤 후보 비교표(`summary.csv`, `pairs.csv`) | 판정 반영 후 채점(이 라운드는 세션 스크립트, 공식 evaluator 함수 사용) | 추적 |
| `pooling_runs/` | supplement_v2 보충 판정에 쓴 원본 run(top 100). 실제로 넣은 depth까지의 사본은 `benchmark/.../annotations/supplement_v2/runs/` | 노트북 15번 결과를 내려받음 | 제외 |

## 현재 기록 (val 124개 쿼리, 오타 쿼리 비활성 + final_v1_val 판정 후 qrels)

| run | 학습 데이터 | nDCG@10 | P@10 | MRR@100 | R@100 | Bpref | 비고 |
|---|---|---|---|---|---|---|---|
| `qwen3_embedding_0_6b` | — (zero-shot) | 0.920 | 0.918 | 0.939 | 0.375 | 0.355 | 기준 비교용 |
| `..._ft_kse1_20261006_0708` | `067e4aa4`(237 쿼리, 오타 포함) | 0.954 | 0.955 | 0.969 | 0.428 | 0.414 | 첫 학습(bf16 에뮬레이션), KEEP |
| `..._ft_kse13_20261013_0543` | `067e4aa4` | 0.953 | 0.952 | 0.968 | 0.426 | 0.412 | fp16 기준선 재현 |
| `..._ft_kse13_20261013_0721` | `067e4aa4` | 0.950 | 0.950 | 0.963 | 0.423 | 0.408 | 오타 증강 ×2 — 채택 안 함 |
| `..._ft_kse14_20261014_0440` | `ec3a9b61`(215 쿼리) | 0.949 | 0.946 | 0.967 | 0.417 | 0.402 | 이전 기준선(2 epoch, LoRA r16, GIST), KEEP |
| `..._ft_kse16_20261016_0012` | `ec3a9b61` | 0.953 | 0.951 | 0.973 | 0.429 | 0.414 | **Qwen3 기준선**(kse14 + hard negative 6), KEEP |
| `bge_m3_ft_mj_20261014_0743` | `ec3a9b61` | 0.960 | 0.963 | 0.974 | 0.444 | 0.437 | **임베딩 v1 선택**(bge-m3 full FT 기본값), KEEP |
| `snowflake_arctic_embed_l_v2_ko_ft_lee_20261015_1434` | `067e4aa4` | 0.961 | 0.965 | 0.981 | 0.458 | 0.447 | Arctic-KO, val HP 탐색 11회 중 1등(30 step), KEEP |

**임베딩 v1 후보 3종 비교**(final_v1_val 판정 후, zero-shot 포함): `model_comparison/final_v1_val/summary.csv`(지표·bad@3·95% CI),
`pairs.csv`(쌍별 Δ·p). 세 후보는 서로 Δ ≤ 0.008, p ≥ 0.28로 같은 수준 — 해석은 `docs/EMBEDDING_V1_PLAN.md` 1-1절.
bge-m3·Arctic 행의 `experiments.csv` Δ·p는 zero-shot이 아니라 **kse16 대비**다(두 계열의 zero-shot 전체 run이 저장소에 없음).

Recall@100·Bpref가 낮은 건 쿼리 하나에 정답이 평균 114개(100개 초과 쿼리 65%)라서다 — 구조적 상한이 약 0.85이고, 모델 간 차이로만 본다
(`docs/EMBEDDING_V1_PLAN.md` 1절). 전체 지표와 신뢰구간은 `artifacts/evaluation/storesearch_ko_v1/*_evaluation.json`.

kse1·kse13은 오타 비활성 전 데이터로 학습했다(평가는 모두 현재 qrels로 다시 채점됨). 같은 설정도 다시 돌리면 ±0.005 흔들리므로
kse1·kse13·kse14 사이 차이는 잡음 수준이다.
