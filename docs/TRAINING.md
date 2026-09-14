# 임베딩 모델 Fine-tuning (Colab)

`docs/MODELING.md`의 zero-shot 비교가 끝난 뒤, 실제로 모델을 우리 데이터에 맞게
학습시키는 단계입니다. 평가 코드는 새로 만들지 않습니다 — fine-tuning으로 나온 모델도
`configs/models/*.yaml`에 등록해서 기존 `14_run_model_eval.py`/`15_score_model_runs.py`로
그대로 채점합니다("run을 채점하는 evaluator는 하나만 둔다", `docs/MODELING.md` 참고).

## 사전 조건

train qrels(`benchmark/storesearch_ko_v1/qrels_train.csv`, 없으면
`qrels/provisional_v1/qrels_train_provisional.csv`)가 있어야 합니다. `docs/PIPELINE.md` 4절
(`08_make_full_annotation_sheets.py` → 사람이 train 시트 채움 → `09_prepare_full_annotations.py`)
까지 끝나면 준비됩니다 — val/test의 adjudication을 기다릴 필요는 없습니다(train은 애노테이터
1명의 단일 라벨링이라 더 빨리 끝납니다).

## 프레임워크를 두 갈래로 나눈 이유

| 트랙 | 대상 모델 | 스크립트 | 왜 |
|---|---|---|---|
| **Qwen3 (메인)** | `qwen3_0_6b`/`4b`/`8b` | `colab/run_finetune_qwen3.py` | `ms-swift`는 Qwen 계열(ModelScope/Alibaba)의 공식 학습 도구라 Qwen3-Embedding 지원이 가장 빠르고 탄탄함. LoRA + 4bit 양자화(QLoRA)로 무료 Colab GPU(T4, ~15GB)에서도 4B/8B까지 시도 가능 |
| **Snowflake/BGE (간단 비교용)** | `arctic_ko`, `bge_m3` 등 | `colab/run_finetune_simple.py` | sentence-transformers 표준 `.fit()` — 어떤 HF 인코더에도 통하는 범용 방식. ms-swift보다 API가 안정적이라 빠르게 결과만 확인할 때 적합 |

`pyproject.toml`의 `train = ["ms-swift"]`는 이미 선언돼 있던 의도를 그대로 따른 것입니다.

## 1. 학습 데이터 준비 (로컬, GPU 불필요)

```bash
python scripts/prepare_finetune_dataset.py
```

- train qrels + `queries.csv` + corpus로부터 `data/finetune/train_pairs.jsonl`을 만듭니다.
- 각 줄: `{"query_id", "query", "positive", "negatives": [...]}`
- **positive**: 그 query의 candidate pool에서 `relevance >= binary_relevance_threshold`(기본 2)인 문서
- **negatives**: 같은 query의 같은 pool에서 relevance가 그 미만인 문서(최대 `--max-negatives`개,
  relevance=1인 경계 사례를 relevance=0보다 우선 — 무작위 negative보다 훨씬 어려운/유용한 negative).
  pooling(06~07) 단계가 이미 BM25/TF-IDF로 모아둔 후보이고 train qrels가 그 전체에 대한 사람 판정이라
  추가 검색 없이 바로 재사용됩니다.
- positive가 하나도 없는 query(=pool 전체가 낮은 relevance)는 제외되고 로그에 개수가 찍힙니다.

## 2-A. Qwen3 fine-tuning (ms-swift, LoRA)

Drive에 `project/src/store_search_ai/`(model_manifest.json 기록용) + `project/data/finetune/train_pairs.jsonl`을
올리면 됩니다(모델 자체는 HF Hub에서 바로 받음). `colab/run_finetune_qwen3.py`를 Colab에서 실행:

- `MODEL_ID`/`TAG`만 바꾸면 0.6B/4B/8B 전환 (`Qwen/Qwen3-Embedding-{0.6B,4B,8B}`)
- 4B/8B는 `USE_4BIT = True` 권장(무료 T4 메모리 제약), `BATCH_SIZE`도 4~8로 낮출 것
- **주의**: `swift sft` 플래그명은 스크립트에 best-effort로 적어뒀지만 ms-swift는 빠르게 바뀌는
  라이브러리라 실행 전 Colab에서 `!swift sft --help`로 실제 플래그를 반드시 확인하세요
  (`--task_type`, `--loss_type`, 4bit 양자화 관련 플래그가 버전별로 다를 수 있음).
- LoRA adapter만 저장되므로, 평가 전에 베이스 모델과 merge가 필요할 수 있습니다
  (`swift export --adapters ... --merge_lora true` 등 — 역시 `--help`로 확인).

## 2-B. Snowflake/BGE 간단 fine-tuning (sentence-transformers)

Drive에 `project/src/store_search_ai/` + `project/data/finetune/train_pairs.jsonl` +
`project/configs/models/<베이스모델>.yaml`을 올리고 `colab/run_finetune_simple.py`에서
`MODEL_CONFIG_PATH`만 바꿔 실행합니다. `arctic_ko.yaml`, `bge_m3.yaml` 등 `configs/models/*.yaml`에
있는 어떤 모델에도 그대로 씁니다.

## 3. 결과 회수 + 평가

1. Drive의 `runs/finetune/<태그>/`를 통째로 내려받아 로컬 `models/<태그>/`에 둡니다
   (`models/`는 `.gitignore`에 등록돼 있어 git에는 안 올라갑니다 — 용량이 크기 때문).
   이 폴더 안에 가중치와 함께 `model_manifest.json`도 들어있습니다(4절 참고).
2. `configs/models/<태그>.yaml`을 새로 만듭니다:
   ```yaml
   name: <태그>
   model_id: models/<태그>          # 로컬 경로 — SentenceTransformer()가 HF Hub ID처럼 그대로 로드함
   query_prompt_name: null          # 베이스 모델이 쓰던 값을 그대로 유지(예: qwen3 계열은 "query")
   normalize_embeddings: true
   target_dimension: null
   batch_size: 32
   ```
3. 기존 zero-shot harness로 그대로 평가:
   ```bash
   python scripts/14_run_model_eval.py --model-config configs/models/<태그>.yaml --split val
   python scripts/15_score_model_runs.py --split val
   ```
   zero-shot 때 만든 `leaderboard_val.csv`에 fine-tuned 모델도 같은 표에 나란히 비교됩니다.
   **`14_run_model_eval.py`가 이 평가 결과를 `model_manifest.json`의 `evaluations`에도 자동으로
   추가합니다** — 별도 조치 필요 없음.

## 4. model_manifest.json — 나중에 서비스에 가져다 쓸 체크포인트 추적

가중치 파일만 있으면 몇 달 뒤엔 "이 폴더에 있는 모델이 정확히 무엇으로, 어떤 데이터로, 어떤
설정으로 학습됐고 성능이 어땠는지" 알 방법이 없어집니다. 그래서 `write_model_manifest()`/
`append_model_manifest_evaluation()`(`src/store_search_ai/pipeline/common.py`)이 학습 스크립트가
끝날 때 자동으로 `models/<태그>/model_manifest.json`을 만들고, 평가할 때마다 결과를 추가합니다.
서비스에 어떤 체크포인트를 배포할지 고를 때 이 파일 하나만 보면 됩니다:

```json
{
  "tag": "qwen3_embedding_0_6b_ft_v1",
  "base_model_id": "Qwen/Qwen3-Embedding-0.6B",
  "framework": "ms-swift+lora",
  "created_at": "2026-09-14T12:34:56+00:00",
  "hyperparameters": { "lora_rank": 16, "num_train_epochs": 3, "...": "..." },
  "training_data": { "source": "...", "sha256": "...", "num_examples": 237 },
  "evaluations": [
    { "evaluated_at": "...", "split": "val", "template": "t1_minimal",
      "tag": "qwen3_embedding_0_6b_ft_v1_val", "metrics": { "nDCG@10": 0.51, "...": "..." } }
  ]
}
```

이 파일은 `models/`와 함께 `.gitignore` 대상이라(가중치와 같은 폴더에 있으므로) git에는 안
올라갑니다 — 팀과 공유하려면 체크포인트 폴더(가중치+manifest)를 통째로 공유 스토리지에 두세요.
서빙 인프라(API, ANN 인덱스 등)는 아직 이 저장소 범위 밖입니다 — 이 매니페스트는 "어떤 체크포인트를
배포할지" 결정하는 데 필요한 최소한의 추적 정보만 제공합니다.

## 재현성 메모

`data/finetune/train_pairs.jsonl`은 qrels_train + corpus + queries.csv로부터 결정적으로
재생성되는 파생 파일입니다. train qrels가 갱신되면(추가 애노테이션 등)
`prepare_finetune_dataset.py`를 다시 돌리고 Colab 학습도 다시 하면 됩니다.
