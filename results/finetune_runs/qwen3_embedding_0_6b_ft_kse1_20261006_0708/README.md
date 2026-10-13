# qwen3_embedding_0_6b_ft_kse1_20261006_0708 — Qwen3-Embedding-0.6B LoRA baseline (KEEP)

| 항목 | 값 |
|---|---|
| 학습 | 2026-10-06, Colab Tesla T4, `precision: bf16`(T4 에뮬레이션 — 아래), 456 step, 4,179초, 최대 GPU 6.76GB |
| 설정 | 노트북 기본값(`NOTE = "baseline"`): LoRA r16·lr 1e-4·epoch 2·batch 32(mini 16)·CachedGIST·negative 3·positive 상한 32 |
| 학습 데이터 | `train_pairs.jsonl` sha256 `067e4aa4…`(query 237개, 7,270행, final qrels) |
| 저장 | LoRA merge → float16, 재로드 검증 통과(`serving.saved_dtype=float16`) |
| val (eval_dtype float16, 코퍼스 214,043) | nDCG@10 **0.5043** (zero-shot 0.3915, Δ +0.1128, p=0.0001, 96/24/16), Bpref 0.3310 (Δ +0.0736, 122/14/0) |

## 파일
- `model_manifest.json` — 설정·데이터 해시·환경·서빙 값·평가 기록(자동)
- `eval_config.yaml` — 이 모델의 평가 설정(`configs/models/<TAG>.yaml`과 같음)
- `notebook_code.py` — 학습한 Colab 세션에서 실행한 셀 코드 전체(실행 순서대로, 같은 셀이 여러 번 있으면 마지막 것이 실제로 쓰인 코드)
- `train_eval_pre.ipynb` — **이 체크포인트를 학습할 때 쓴 노트북 파일**(팀원이 보관한 학습 당시 버전)

## 학습 당시 노트북과 지금 노트북의 차이
`train_eval_pre.ipynb`는 2026-10-07 수정 전 버전이라 지금 `colab/train_eval.ipynb`와 다음이 다릅니다(학습 방식 자체 — 데이터, loss, LoRA,
하이퍼파라미터 — 는 같음):
- 학습 정밀도를 `torch.cuda.is_bf16_supported()`로 골라 **T4에서 bf16(하드웨어 가속 없는 에뮬레이션)으로 학습**됨. bf16 AMP는 정상적인
  학습 방식이라 모델은 유효하지만, 지금 노트북으로 T4에서 학습하면 fp16이므로 정밀도가 다릅니다(`docs/TRAINING.md` 6절).
- GIST guide 모델은 fp16, 평가는 dtype을 지정하지 않음 → 위 val 숫자는 **지금 노트북으로 다시 평가한 결과**(기준·학습 모델 모두 float16).
- 그 밖에: 학습 실패 시 `final_dir` 초기화, 평가 dtype 기록·리더보드 열, SMOKE 정밀도 확인, SMOKE/데이터 불일치 방지(채점·학습 로직과 무관).

모델 가중치(`models/qwen3_embedding_0_6b_ft_kse1_20261006_0708/`, 1.2GB)는 git에 올리지 않습니다 — 팀 공유 스토리지에 보관.
