# bge_m3_ft_mj_20261014_0743 — bge-m3 full fine-tuning, 노트북 기본값 (임베딩 v1 후보)

**manifest·체크포인트가 저장소에 없다.** 아래 값은 담당자가 넘긴 노트북 `train_eval_bge.ipynb`(이 폴더)의 설정 셀과 실행 출력에서 옮겼다.
Drive `runs/finetune/bge_m3_ft_mj_20261014_0743/`에 모델이 저장됐고 KEEP 표시 셀도 실행돼 있다 — v1으로 고르려면 그 폴더를 받아
`import_colab_results.py --models bge_m3_ft_mj_20261014_0743`으로 가져온다.

| 항목 | 값 |
|---|---|
| 노트북 | 저장소 `colab/train_eval.ipynb` @ `ccead76`(2026-10-14)와 셀 코드 동일 — 바꾼 건 `OWNER="mj"`, `MODEL="bge_m3"`, `NOTE`, KEEP 한 줄뿐 |
| 학습 | 2026-10-14, Colab Tesla T4, `precision: fp16`, 416 step(2 epoch), 917초, 최대 GPU 10.93GB |
| 설정 | preset `bge_m3` 기본값: full FT, lr 2e-5, batch 32(mini 16), CachedGIST(guide = bge-m3), hard negative 3, positive 상한 32, warmup 0.1 |
| 학습 데이터 | 215 쿼리, 6,650행(오타 비활성 후) — kse14·kse16과 같은 데이터로 보이지만 sha는 manifest가 없어 확인 못 함 |
| 저장 | float16, 재로드 검증 통과(최소 cosine 1.00000) |
| HP 탐색 | 없음(기본값 1회) |

## val (124 쿼리, final_v1_val 판정 후 qrels)

| | nDCG@10 [95% CI] | P@10 | MRR@100 | R@100 | Judged@10 | bad@3 | 1위 정답률 |
|---|---|---|---|---|---|---|---|
| bge-m3 zero-shot¹ | 0.918 [0.887, 0.944] | 0.930 | – | – | 0.982 | 23/124 | 0.927 |
| **이 run** | **0.960** [0.936, 0.980] | 0.963 | 0.974 | 0.444 | 0.994 | 8/124 | 0.960 |

- zero-shot 대비 **+0.042 (p=0.0001, 40/78/6)** — 세 계열 중 학습 효과가 가장 크다. Qwen3 kse16 대비 +0.007(p=0.45, 같은 수준).
- 판정 전 공식 nDCG는 0.840이었다(상위 10개 중 189쌍 미판정). 노트북 출력의 "zero-shot 대비 −0.078"은 그 때문이고 실제로는 개선이다.

¹ zero-shot은 supplement_v2 pooling run(depth 20)으로 계산 — @10·@3 지표만 유효.
