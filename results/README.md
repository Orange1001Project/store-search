# results/ — 실험 결과 기록

모델 가중치는 여기 두지 않는다(`models/`, git 제외 — `.gitignore`가 `results/` 아래 `*.safetensors`·`*.bin`도 막음).
Colab 결과는 손으로 복사하지 말고 `scripts/import_colab_results.py --drive-dir <내려받은 store-search-ai> --verify`로 가져온다
(`docs/TRAINING_TEAM.md` 9절).

| 경로 | 내용 | 만드는 곳 | git |
|---|---|---|---|
| `experiments.csv` | **실험 기록표** — 공식 평가 하나당 한 줄(모델, 누가, NOTE, 학습 데이터 sha, GPU, precision, 지표, 기준 대비 Δ·p, KEEP) | `import_colab_results.py`, 지표 갱신은 `rescore_evaluations.py` | 추적 |
| `model_eval/<run 이름>/run_t1_minimal_val.csv` | 공식 평가에 쓴 검색 결과(쿼리별 상위 100). 평가 json은 `artifacts/evaluation/storesearch_ko_v1/` | `import_colab_results.py` | 추적 |
| `finetune_runs/<TAG>/` | 학습 run 기록(`model_manifest.json`, `eval_config.yaml`, `notebook_code.py`) — 가중치 없이 어떤 설정·데이터·코드로 학습했는지 | `import_colab_results.py` | 추적 |
| `stack_eval/<split>/` | **검색 파이프라인 사전 탐색**(하이브리드·reranker, 학습 없음) — `summary.csv`, BM25 캐시, reranker 점수 캐시·채점 쌍, 하이브리드 run | `scripts/eval_retrieval_stack.py` | 일부 추적(다시 만들 수 있는 run 사본은 제외) |
| `judging_candidates/<round>/` | 일괄 판정 후보 run 모음(val+test, 시스템 이름 = 후보 name) | `scripts/collect_judging_candidates.py` | 판정 라운드 때 생성 |
| `pooling_runs/` | supplement_v2 보충 판정에 쓴 원본 run(top 100). 실제로 넣은 depth까지의 사본은 `benchmark/.../annotations/supplement_v2/runs/` | 노트북 15번 결과를 내려받음 | 제외 |

## 현재 기록 (val 124개 쿼리, 오타 쿼리 비활성 후 기준)

| run | 학습 데이터 | nDCG@10 | 비고 |
|---|---|---|---|
| `qwen3_embedding_0_6b` | — (zero-shot) | 0.920 | 기준 비교용 |
| `..._ft_kse1_20261006_0708` | `067e4aa4`(237 쿼리, 오타 포함) | 0.954 | 첫 학습(bf16 에뮬레이션), KEEP |
| `..._ft_kse13_20261013_0543` | `067e4aa4` | 0.953 | fp16 기준선 재현 |
| `..._ft_kse13_20261013_0721` | `067e4aa4` | 0.949 | 오타 증강 ×2 — 채택 안 함 |
| `..._ft_kse14_20261014_0440` | `ec3a9b61`(215 쿼리) | 0.948 | **현재 기준선**(2 epoch, LoRA r16, GIST), KEEP |

kse1·kse13은 오타 비활성 전 데이터로 학습했다(평가는 모두 현재 qrels로 다시 채점됨). 같은 설정도 다시 돌리면 ±0.005 흔들리므로
kse1·kse13·kse14 사이 차이는 잡음 수준이다. `stack_eval/val/summary.csv`의 하이브리드·reranker 수치는 파이프라인 설계용 사전 탐색이며
임베딩 v1 선택에는 쓰지 않는다(`docs/EMBEDDING_V1_PLAN.md`).
