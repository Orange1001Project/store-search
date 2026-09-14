# 모델 비교 / 평가 구조 (BEIR 스타일)

임베딩 모델을 파인튜닝하기 전에, 여러 후보 모델을 같은 벤치마크·같은 evaluator로 공정하게 비교해야
합니다. 이 부분은 [BEIR](https://github.com/beir-cellar/beir)이 채택한 3단 분리 구조를 그대로 따릅니다.

```
텍스트 → [Encoder]      텍스트를 벡터로 바꾸는 것만 안다
       → [ExactSearch]  벡터로 top-k run을 만드는 것만 안다
       → [Evaluator]    run을 채점하는 것만 안다 (scripts/13_evaluate_run.py, 모두가 공유하는 단일 기준)
```

**zero-shot과 fine-tuned을 구분하지 않는 이유**: `configs/models/*.yaml`의 `model_id`가 HF Hub ID(zero-shot)든
로컬 경로(fine-tuned, `docs/TRAINING.md` 참고)든 `SentenceTransformerEncoder`는 완전히 동일하게
로드합니다. 그래서 이 평가 스크립트들의 이름에는 "zero_shot"을 쓰지 않습니다 — zero-shot 비교
단계에서 쓰던 이름이지만 지금은 fine-tuned 모델도 같은 경로로 평가되기 때문입니다.

## 왜 이렇게 나눴는가

nDCG/Recall/Precision/MRR을 여러 곳에서 각자 재구현하면 언젠가 한쪽만 고치는 실수가 생기고, 그러면
"어느 숫자가 맞는 숫자인지" 아무도 확신할 수 없게 됩니다. 그래서 이 구조에서는 metric 계산을
`scripts/13_evaluate_run.py` 한 곳에만 두고:

- `scripts/14_run_model_eval.py`가 run.csv를 만든 뒤, **`scripts/13_evaluate_run.py`를 그대로
  서브프로세스로 호출**해서 채점합니다. 코드를 복사하지 않고 같은 프로세스를 그대로 재사용하므로,
  숫자가 어긋날 여지 자체가 없습니다.

## 모듈 구성

| 모듈 | 역할 |
|---|---|
| `src/store_search_ai/models/base.py` | `BaseEncoder` 추상 인터페이스 (`encode_corpus`, `encode_queries`, `name`) |
| `src/store_search_ai/models/sentence_transformer_encoder.py` | `configs/models/*.yaml` 하나를 읽어 실제 sentence-transformers 모델을 로드 |
| `src/store_search_ai/models/random_encoder.py` | 네트워크·GPU 없이 배관만 검증하는 가짜 인코더 (숫자 자체는 무의미) |
| `src/store_search_ai/retrieval/exact_search.py` | `ExactCosineSearch` — 코퍼스 임베딩 전체와 코사인 유사도로 top-k 계산 |
| `scripts/14_run_model_eval.py` | (로컬 GPU가 있을 때) 위 셋을 엮어서 corpus 인코딩 → query 인코딩 → 검색 → run.csv → `13_evaluate_run.py` 호출까지 한 번에 |
| `scripts/15_score_model_runs.py` | `results/model_eval/` 밑의 여러 run(Colab/로컬, zero-shot/fine-tuned 어느 쪽에서 왔든)을 한 번에 채점해 리더보드 생성 |
| `colab/run_model_eval_encoding.py` | Colab(GPU)에서 같은 인코더/검색 코드를 재사용해 run.csv를 생성 (`colab/README.md` 참고) |

## 실행 예시

**Colab (GPU)에서 인코딩하는 경우** — 실제로 이 프로젝트가 쓰는 방식입니다. `colab/README.md`에
전체 절차가 있습니다. 요약하면: VSCode 프로젝트의 `src/`, `configs/models/`, corpus, queries.csv를
Drive에 올려두고, `colab/run_model_eval_encoding.py`가 **같은 `SentenceTransformerEncoder`/
`ExactCosineSearch`**로 인코딩·검색해서 `run.csv`를 만듭니다. 그 파일을 `results/model_eval/`로
가져오면, 아래 로컬 명령과 완전히 동일하게 채점됩니다. 자세한 사항은 `colab/README.md` 참고하세요.

**로컬에 GPU가 있는 경우**:

```bash
# 네트워크 없이 배관만 검증 (CI/스모크 테스트용)
python scripts/14_run_model_eval.py --dummy --split val

# 실제 모델 비교 (pip install -e ".[embedding]" 먼저 필요 — torch/sentence-transformers)
python scripts/14_run_model_eval.py --model-config configs/models/bge_m3.yaml --split val
python scripts/14_run_model_eval.py --model-config configs/models/qwen3_0_6b.yaml --split val
```

각 실행은 `results/model_eval/<모델명>/run_<template>_<split>.csv`를 만듭니다. 모델이 여러 개
쌓이면 하나씩 채점하는 대신:

```bash
python scripts/15_score_model_runs.py --split val
```

로 `results/model_eval/` 밑의 모든 run을 한 번에 채점해서 `leaderboard_val.csv`(nDCG@10 기준 정렬)를
만듭니다. val 기준으로 가장 좋은 후보를 골라 파인튜닝을 시작하면 됩니다(`docs/TRAINING.md`).
Fine-tuned 모델의 run도 같은 폴더/스키마로 만들어지므로, 파인튜닝 후에는 zero-shot 결과와
fine-tuned 결과가 같은 리더보드에 나란히 비교됩니다.

**검증 완료**: `--dummy`(무작위 벡터, nDCG@10 ≈ 0.003)와 TF-IDF 문자 n-gram 벡터(실제 신호 있음,
nDCG@10 ≈ 0.61)로 실제 실행해서 두 결과가 확연히 다르게 나오는 것을 확인했습니다 — 검색 로직 자체가
올바르게 연결되어 있다는 뜻입니다. `15_score_model_runs.py`도 서로 다른 두 개의 더미 run(모델
2개를 흉내)을 만들어 실제로 리더보드가 nDCG@10 기준으로 올바르게 정렬되는 것까지 확인했습니다.

## 확장 지점 (Qdrant 등 ANN으로 갈 때)

`ExactCosineSearch`의 생성자·`search()` 시그니처(코퍼스 임베딩+doc_id → 쿼리 임베딩+query_id →
동일 스키마의 run)만 유지하면, 내부 구현을 Qdrant/FAISS 같은 ANN 인덱스로 바꿔도 `14_run_model_eval.py`나
서빙 코드는 손댈 필요가 없습니다. 이것이 이 구조를 BEIR 패턴으로 맞춘 이유입니다 — 후보 비교 단계에서는
정확한 코사인 유사도로, 서비스 단계에서는 ANN으로, 같은 인터페이스 위에서 교체됩니다.
