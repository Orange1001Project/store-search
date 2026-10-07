# Colab — `train_eval.ipynb` 하나로 학습·평가

GPU가 필요한 일(학습, 21만 개 문서 인코딩·채점)은 Colab에서 이 노트북 하나로 합니다. **학습·평가 코드가 전부 노트북 안에** 있어서
`src/`를 올리지 않고, 기법(학습 데이터 만드는 방식, LoRA·loss, 학습 인자)을 셀에서 바로 고쳐 실험합니다.

```
[처음 한 번]    로컬: python scripts/pack_for_colab.py → colab_upload/data/ 를 Drive store-search-ai/data/ 로 업로드
               Colab: 파일 > 노트북 업로드 → colab/train_eval.ipynb, SMOKE=True로 끝까지 실행해 "통과" 확인
[반복 — Colab]  설정·기법 수정 → 학습 → val 공식 채점(기준 대비 Δ·p) → 리더보드 → 고쳐서 다시
[마지막 한 번]  Drive store-search-ai 내려받기 → 로컬: python scripts/import_colab_results.py --drive-dir ... --verify
```

- 노트북을 고쳐도 다시 올리는 건 **그 파일 하나**, 데이터는 바뀔 때만 다시 올립니다.
- 고치는 방법 두 가지(`docs/TRAINING_TEAM.md` 3절):
  - **A. Colab에서 바로** — 작은 수정. 고친 셀 → 8. 학습 → 9. 평가 → 10. 리더보드(세션 유지). 끝나면 파일 > 다운로드 > .ipynb로 받아
    이 폴더의 `train_eval.ipynb`에 덮어쓰기(정본은 저장소 파일).
  - **B. VS Code(Claude)에서** — 큰 수정. 이 파일을 고친 뒤 Drive `내 드라이브/Colab Notebooks/train_eval.ipynb`(이전 사본)를 지우고
    다시 업로드 → 위에서부터 실행.
- 셀별 코드 설명: `docs/TRAIN_EVAL_NOTEBOOK.md`.
- 셀 구성·고쳐도 되는 곳·기록 규칙: `docs/TRAINING_TEAM.md`.
- **`7. 평가` 셀은 고치지 않습니다** — 로컬 공식 evaluator(`scripts/13_evaluate_run.py`)와 같은 채점 로직이고,
  `tests/test_train_eval_notebook.py`가 노트북 셀을 실제로 실행해 공식 evaluator와 같은 결과인지 확인합니다.
  가져올 때 `import_colab_results.py --verify`도 로컬에서 다시 채점해 확인합니다.
- 라이브러리: Colab 기본 torch·transformers·sentence-transformers·peft를 그대로 쓰고(다운그레이드 안 함), 채점용
  `ir-measures`·`pytrec-eval-terrier`만 설치, peft와 충돌하는 Colab 기본 `torchao`는 지웁니다. 버전 차이는 `2. 호환` 셀이 맞춥니다.

## Drive 구조 (`내 드라이브/store-search-ai/`)

```
data/                       ← pack_for_colab.py 결과(학습 데이터·corpus·queries·qrels·data_version.json)
runs/finetune/<TAG>/        ← 모델 + model_manifest.json + eval_config.yaml + notebook_code.py(그 모델을 만든 셀 코드)
runs/model_eval/<tag>/      ← run_<template>_<split>.csv (검색 결과)
runs/evaluation/            ← <tag>_<template>_<split>_evaluation.json, _per_query.csv (지표)
runs_smoke/                 ← SMOKE=True 결과(지워도 됨)
```
