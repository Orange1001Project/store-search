# Colab 노트북 — 학습·평가를 Colab 안에서 끝내기

GPU가 필요한 일(학습, 21만 개 문서 인코딩)은 Colab에서 하고, **채점까지 Colab에서 바로** 합니다. 학습 → 평가 → 코드·설정
수정 → 다시 학습을 Colab 안에서 반복하고, 실험이 다 끝나면 결과만 VS Code 저장소로 가져와 저장합니다.

```
[처음 한 번]      로컬: python scripts/pack_for_colab.py → colab_upload/project 를 Drive store-search-ai/project 로 업로드
[반복 — Colab]    학습 노트북: 설정 → 학습 → val 공식 채점(기준 대비 Δ·p) → 리더보드 → 고쳐서 다시
[마지막 한 번]    Drive store-search-ai 내려받기 → 로컬: python scripts/import_colab_results.py --drive-dir ... --verify
```

## 노트북

| 노트북 | 용도 |
|---|---|
| `smoke_test_finetune.ipynb` | 처음 한 번: 가짜 데이터로 학습 → 평가 → 리더보드까지 전체 파이프라인 확인(마지막에 `통과`) |
| `run_finetune_simple.ipynb` | Arctic / BGE-M3 학습 + 바로 val 채점 + 리더보드 |
| `run_finetune_qwen3.ipynb` | Qwen3-Embedding 학습(LoRA) + 바로 val 채점 + 리더보드 |
| `run_model_eval_encoding.ipynb` | 여러 모델 한꺼번에 평가(zero-shot 비교표, 여러 run 재평가) + 리더보드 |

- 여는 법: Colab **파일 > 노트북 업로드** → 이 폴더의 `.ipynb`, 또는 **GitHub** 탭에서 브랜치 선택. T4 GPU 런타임으로 열림.
- 노트북에서는 **설정 셀의 값만** 바꿉니다. 로직은 Drive의 `project/src/` 파일을 Colab 편집기에서 고칩니다
  (`docs/TRAINING_TEAM.md` 3-2절). 자세한 사용법·규칙은 `docs/TRAINING_TEAM.md`.
- `.ipynb`는 같은 이름의 `.py`(git·리뷰용 원본)에서 `python scripts/build_colab_notebooks.py`로 생성됩니다 —
  `.py`를 고쳤으면 다시 생성해서 둘 다 커밋하세요(어긋나면 `tests/test_colab_notebooks.py`가 실패).

## 채점은 어디서 해도 같은 점수

Colab의 평가 셀(`store_search_ai.evaluation.model_evaluation.evaluate_model`)은 로컬 `scripts/13_evaluate_run.py`와
**같은 함수**(`store_search_ai.evaluation.evaluator.build_evaluation_report`)로 채점합니다. 결과 파일 이름도 15번과 같아서
(`<tag>_<template>_<split>_evaluation.json`) 가져온 뒤 그대로 이어서 쓸 수 있고, `import_colab_results.py --verify`가 로컬에서
다시 채점해 Colab 점수와 같은지 확인합니다.

- test split은 코드에서 막혀 있습니다(`allow_test=True` / 노트북의 `FINAL_TEST`·`ALLOW_TEST`) — 반복 실험은 val로만.
- smoke test처럼 축소 코퍼스로 돌린 평가는 `official: false`로 저장돼 리더보드·가져오기에서 빠집니다.

## Drive에 쌓이는 것 (`내 드라이브/store-search-ai/`)

```
project/                      ← pack_for_colab.py 결과(코드·설정·학습 데이터·corpus·queries·qrels)
runs/finetune/<TAG>/          ← 학습한 모델 + model_manifest.json(+ 평가 기록) + eval_config.yaml + code_snapshot.zip
runs/model_eval/<tag>/        ← run_<template>_<split>.csv (검색 결과)
runs/evaluation/              ← <tag>_<template>_<split>_evaluation.json, _per_query.csv (지표)
runs/finetune_smoke/          ← smoke test 결과(지워도 됨)
```

## 로컬에서 하고 싶다면

로컬에 GPU가 있으면 예전처럼 `scripts/14_run_model_eval.py` → `scripts/15_score_model_runs.py`로 평가해도 됩니다(같은 evaluator).
