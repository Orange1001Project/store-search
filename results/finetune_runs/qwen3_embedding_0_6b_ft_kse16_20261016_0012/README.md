# qwen3_embedding_0_6b_ft_kse16_20261016_0012 — Qwen3-Embedding-0.6B LoRA, hard negative 6 (KEEP, Qwen3 0.6B 확정 run)

| 항목 | 값 |
|---|---|
| 학습 | 2026-10-16, Colab Tesla T4, `precision: fp16`, 416 step, 2,557초, 최대 GPU 6.49GB |
| 설정 | kse14와 같음(LoRA r16·lr 1e-4·epoch 2·batch 32(mini 16)·CachedGIST·positive 상한 32) + **hard negative 3 → 6** (`NOTE = "hard negative 3→6 (나머지 기본값, 215 queries)"`) |
| 학습 데이터 | `train_pairs.jsonl` sha256 `ec3a9b61…`(query 215개, 6,650행, final qrels, 오타 쿼리 비활성 후) — kse14와 같음 |
| 저장 | LoRA merge → float16, 재로드 검증 통과(`serving.saved_dtype=float16`) |
| val (eval_dtype float16, 124 쿼리) | nDCG@10 **0.9500** [95% CI 0.923, 0.974] (zero-shot 0.9196, Δ +0.030, p=0.0001) |
| kse14 대비 | nDCG@10 +0.002(p=0.45), MRR@100 +0.007(p=0.38), **Recall@100 +0.012(p=0.0001)**, bad@3 12 → 7/124, 1위 정답률 0.952 → 0.968 |

## 해석
- 공식 nDCG@10은 kse14와 같은 수준(Δ < 0.03). 개선은 상위권 오답(bad@3)과 Recall@100 쪽이다.
- bad@3 변화는 6개 쿼리 해결(책 파는 곳, 생선, 활어, 전자상거래 곡물, 웨이트 운동하는 곳, 자동차추천), 1개 악화(딸기)라 부호 검정 p≈0.13 —
  방향은 맞지만 val 124개로 확정할 수는 없다.
- kse14 학습 loss가 2 epoch 끝에 0.02~0.05로 포화돼 있어 epoch 대신 판정된 hard negative를 늘렸다.

## 파일
- `model_manifest.json` — 설정·데이터 해시·환경·서빙 값·평가 기록(자동)
- `eval_config.yaml` — 이 모델의 평가 설정(`configs/models/<TAG>.yaml`과 같음)
- `notebook_code.py` — 학습한 Colab 세션에서 실행한 셀 코드 전체

학습 당시 노트북은 `colab/train_eval.ipynb`에 hard negative 6 블록을 더한 버전이고, 지금 노트북은 같은 값을 Qwen3 0.6B preset 기본값
(`"num_hard_negatives": 6`)으로 옮겨 두었다 — 학습 방식은 같다.

모델 가중치(`models/qwen3_embedding_0_6b_ft_kse16_20261016_0012/`, 1.2GB)는 git에 올리지 않습니다 — 팀 공유 스토리지에 보관.
