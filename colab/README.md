# Colab에서 임베딩 모델 인코딩/평가하기

이 프로젝트는 GPU가 없는 로컬/VSCode 환경과, GPU가 있는 Colab 환경을 나눠서 씁니다.

```
[VSCode 로컬]                              [Colab]
1. Drive에 프로젝트 업로드
   (src/, configs/models/, data/corpus/,
    benchmark/.../queries.csv)
                                  ──▶
                                       2. run_model_eval_encoding.py 실행
                                          (모델별로 corpus/query 인코딩
                                           → exact cosine 검색 → run.csv)
                              ◀──
3. Drive의 runs/model_eval/ 를
   results/model_eval/ 에 그대로 복사
4. scripts/15_score_model_runs.py
   로 전체 채점 → 리더보드
```

## 1. VSCode → Drive 업로드

Google Drive의 `내 드라이브/store-search-ai/project/` 밑에 아래만 있으면 됩니다 (전체 프로젝트를
zip해서 올리고 그 자리에서 압축 해제해도 됩니다):

```
project/
  src/store_search_ai/              (그대로)
  configs/models/*.yaml             (그대로)
  data/corpus/store_corpus_v002.parquet
  benchmark/storesearch_ko_v1/queries.csv
```

`data/raw/*.xlsx`나 애노테이션 원본은 Colab에 필요 없으므로 올리지 않아도 됩니다.

## 2. Colab에서 실행

`colab/run_model_eval_encoding.py`를 Colab 노트북 셀로 복사해서 실행하세요 (또는 그대로 `.py`로
업로드해서 `%run`으로 실행해도 됩니다). 이 스크립트는:

- Drive에 올려둔 `src/store_search_ai`를 `sys.path`로 그대로 가져다 씁니다 — 즉 로컬에서 쓰는
  `SentenceTransformerEncoder`, `ExactCosineSearch`와 **완전히 같은 코드**로 인코딩·검색합니다.
- `configs/models/*.yaml`에 있는 모델을 전부 순회합니다. 모델을 추가/제외하려면 이 스크립트가
  아니라 `configs/models/`의 yaml 파일을 추가/삭제하세요.
- 결과를 `Drive/store-search-ai/runs/model_eval/<모델명>/run_<template>_<split>.csv`로 저장합니다.

`SPLIT`, `TEMPLATES` 두 변수만 바꾸면 다른 split/template 조합을 돌릴 수 있습니다. 맨 아래
"query prompt 실험" 셀은 특정 모델 하나에 대해 커스텀 instruction을 즉흥적으로 비교해보고 싶을 때만
쓰는 선택 셀입니다.

## 3. Drive → VSCode 로 결과 회수

Drive의 `store-search-ai/runs/model_eval/`를 통째로 내려받아 로컬 프로젝트의 `results/model_eval/`
자리에 그대로 덮어씁니다 (폴더 구조가 이미 동일하게 맞춰져 있습니다).

## 4. VSCode에서 채점

```bash
python scripts/15_score_model_runs.py --split val
```

`results/model_eval/*/run_*_val.csv`를 전부 찾아서 공식 evaluator(`scripts/13_evaluate_run.py`)로
채점하고, `results/model_eval/leaderboard_val.csv`에 nDCG@10 기준 정렬된 비교표를 남깁니다.

모델 하나만 빠르게 확인하고 싶으면 기존처럼:

```bash
python scripts/13_evaluate_run.py --qrels benchmark/storesearch_ko_v1/qrels_val.trec \
    --run results/model_eval/bge_m3/run_t1_minimal_val.csv --tag bge_m3_t1_val
```

## 로컬에 GPU가 있다면

Colab 없이 `scripts/14_run_model_eval.py`를 로컬에서 바로 실행해도 됩니다 (`pip install -e".[embedding]"` 필요). 폴더 구조와 스키마가 동일하므로 `scripts/15_score_model_runs.py`은
Colab 결과와 로컬 결과를 구분 없이 함께 채점합니다.

## Zero-shot 다음 단계: Fine-tuning

zero-shot 비교로 후보 모델을 추린 뒤에는 실제로 학습을 시켜봅니다 — `docs/TRAINING.md` 참고.
`colab/run_finetune_qwen3.py`(Qwen3-Embedding, ms-swift+LoRA), `colab/run_finetune_simple.py`
(Snowflake Arctic/BGE 등, sentence-transformers) 두 스크립트가 있고, 학습 데이터는 로컬에서
`python scripts/prepare_finetune_dataset.py`로 미리 만들어 Drive에 올립니다. Fine-tuned 모델도
`run_model_eval_encoding.py`/`14_run_model_eval.py`로 zero-shot 모델과 완전히 동일하게 평가됩니다
(그래서 이 문서/스크립트들 이름에 "zero_shot"을 쓰지 않습니다).
