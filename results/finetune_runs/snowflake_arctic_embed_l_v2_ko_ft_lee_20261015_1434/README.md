# snowflake_arctic_embed_l_v2_ko_ft_lee_20261015_1434 — Arctic-KO full fine-tuning, val HP 탐색 2단계의 1등 (임베딩 v1 후보, KEEP)

| 항목 | 값 |
|---|---|
| 노트북 | `train_eval_snow.ipynb`(이 폴더) = 저장소 `colab/train_eval.ipynb` @ `b757994`(2026-10-13) + 담당자가 붙인 **17번 HP 튜닝 셀 2개**(`notebook_code.py`에 남아 있음) |
| 학습 | 2026-10-15, Colab NVIDIA L4, `precision: bf16`, **30 step(1 epoch), 43초** |
| 설정 | lr **5e-6**, epoch **1**, positive 상한 **4**(→ 948행), hard negative 3, batch 32(mini 16), CachedGIST, full FT |
| 학습 데이터 | sha `067e4aa4` — **오타 비활성 전 데이터(237 쿼리, 오타 22개 포함)**. Drive data/를 새로 받지 않은 상태 |
| HP 탐색 | 1단계 lr {1e-5, 5e-6, 2e-5} × epoch {1, 2} = 6회 → 2단계 lr 5e-6·1 epoch 고정, positive 상한 {4, 8, 16}·negative {1, 6} = 5회. **val 공식 nDCG@10으로 11개 중 1등을 고름**(그때 qrels는 Judged@10 ≈ 0.95) |

## val (124 쿼리, final_v1_val 판정 후 qrels)

| | nDCG@10 [95% CI] | P@10 | MRR@100 | R@100 | Judged@10 | bad@3 | 1위 정답률 |
|---|---|---|---|---|---|---|---|
| Arctic-KO zero-shot¹ | 0.952 [0.926, 0.975] | 0.961 | – | – | 0.997 | 9/124 | 0.952 |
| **이 run** | **0.961** [0.937, 0.982] | 0.965 | 0.981 | 0.458 | 0.997 | 6/124 | 0.976 |

- zero-shot 대비 +0.009(p=0.016, 16/102/6). 30 step·lr 5e-6이라 가중치가 베이스에서 거의 움직이지 않았고, 11개 설정 중 val 1등을 고른 값이라
  이 +0.009에는 **선택 편향**이 섞여 있다(같은 설정 재실행 흔들림 ±0.005 × 11회 중 최댓값 ≈ +0.008). 사실상 **zero-shot Arctic-KO와 같은 모델**로 본다.
- Qwen3 kse16 대비 +0.008(p=0.28), bge-m3 mj 대비 +0.001(p=0.84) — 같은 수준.

¹ zero-shot은 supplement_v2 pooling run(depth 20)으로 계산 — @10·@3 지표만 유효.
