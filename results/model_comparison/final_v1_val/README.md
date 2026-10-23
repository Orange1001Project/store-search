# final_v1_val 후보 비교표

final_v1_val 판정을 반영한 qrels_val(124 쿼리)로 채점했다. 세션 스크립트로 만들었고, 채점에는 공식 evaluator 함수를 썼다.

- `summary.csv`: 모델별 지표.
  - `nDCG@10`: 공식 값이다. 판정 없는 문서를 0점으로 센다.
  - `condensed nDCG@10`: 판정된 문서만 남겨 순위를 다시 매긴 값이다(Sakai 2007). 판정 누락에 강하다.
  - `unjudged@10`: 상위 10개 중 판정 없는 문서 수다.
  - `bad@3`: 상위 3개에 정답(2점 이상)이 하나도 없는 쿼리 비율이다. 판정 없는 문서도 오답으로 세므로 판정 누락에 **약하다**.
  - `Δ vs Qwen3 kse16`, `p`: 공식 nDCG@10 기준이다.
- `pairs.csv`: 쌍별 공식 nDCG@10 차이 [95% CI], paired permutation p, wins/ties/losses.

## `*` 표시

`*`가 붙은 모델은 final_v1_val 판정 라운드의 후보가 **아니었다**. 그래서 supplement_v2 pooling run(depth 20)으로 계산했다.

- 이 라운드에서 상위 결과를 판정받지 않았기 때문에 판정 누락이 많다(bge-m3 zero-shot은 상위 10개 중 23개).
- 그래서 공식 nDCG@10과 bad@3가 실제보다 낮게(나쁘게) 나온다.
- 이 모델과 비교할 때는 `condensed nDCG@10`을 함께 본다.
- run 깊이가 20이라 @10·@3 지표만 유효하다.

## zero-shot 대비 학습 효과 — 공식 값과 condensed 값 (2026-10-19, PR #4 리뷰 반영)

| 비교 | 공식 Δ nDCG@10 | condensed Δ [95% CI] | condensed p | w/t/l |
|---|---|---|---|---|
| bge-m3 mj vs bge-m3 zero-shot* | +0.042 | **+0.029** [0.013, 0.048] | 0.0005 | 28/91/5 |
| Qwen3 kse16 vs Qwen3 zero-shot | +0.034 | +0.034 [0.021, 0.049] | 0.0001 | 36/84/4 |
| Arctic-KO lee vs Arctic-KO zero-shot* | +0.009 | +0.008 [0.001, 0.015] | 0.025 | 14/106/4 |

- bge-m3 공식 Δ 0.042 가운데 약 0.013은 zero-shot의 판정 누락 때문이다. 판정 누락을 걷어 내도 학습 효과(+0.029)는 유의하다.
- 후보끼리 condensed 비교에서도 결론은 같다.
  - bge-m3 mj vs kse16: +0.012 [−0.001, 0.029], p=0.11
  - Arctic lee vs bge-m3 mj: −0.002, p=0.71
