# -*- coding: utf-8 -*-
"""store_search_ai_colab_model_eval_encode.ipynb

Colab에서 실행: 모델 로드 → corpus/query 인코딩 → exact cosine 검색 → run.csv 생성.
`configs/models/*.yaml`이 zero-shot 모델(HF Hub ID)이든 fine-tuned 모델(로컬 경로,
`docs/TRAINING.md` 참고)이든 완전히 같은 코드로 처리한다 — 그래서 폴더/스크립트 이름에
"zero_shot"을 쓰지 않는다.
채점(scores)은 여기서 하지 않는다 — run.csv를 VSCode 프로젝트로 가져가서
`scripts/15_score_model_runs.py`(공식 evaluator)로 한다. 이유는
docs/MODELING.md의 "왜 이렇게 나눴는가" 참고: metric 계산은 한 곳에서만 한다.

사용 전 준비 (한 번만):
  1. 로컬 VSCode 프로젝트에서 Google Drive에 아래를 업로드해둔다.
       내_드라이브/store-search-ai/project/src/store_search_ai/   (그대로 폴더째)
       내_드라이브/store-search-ai/project/configs/models/*.yaml
       내_드라이브/store-search-ai/project/data/corpus/store_corpus_v002.parquet
       내_드라이브/store-search-ai/project/benchmark/storesearch_ko_v1/queries.csv
     (즉 VSCode 프로젝트 폴더를 그대로 zip해서 Drive에 올리고 압축만 풀어도 된다.)
  2. 이 스크립트를 Colab에서 실행한다.
  3. 끝나면 내_드라이브/store-search-ai/runs/model_eval/ 를 통째로 내려받아
     로컬 프로젝트의 results/model_eval/ 밑에 그대로 덮어쓴다.
"""

import torch

print("CUDA:", torch.cuda.is_available())
if torch.cuda.is_available():
    print(torch.cuda.get_device_name(0))
    print(round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 2), "GB")

# 라이브러리 설치 (store_search_ai 자체는 numpy/pandas/pyyaml만 있으면 되므로 별도 설치 불필요 —
# 아래 sys.path.insert로 VSCode 프로젝트의 src/를 그대로 가져다 쓴다)
get_ipython().system(
    # 학습(colab/run_finetune_*.py)과 같은 버전 — zero-shot과 fine-tuned 모델을 같은 라이브러리로 인코딩해야 비교가 공정하다
    'pip -q install "sentence-transformers==3.4.1" "transformers==4.51.3" "peft==0.15.2" '
    '"datasets==3.5.0" "accelerate==1.6.0"'
)

from google.colab import drive

drive.mount("/content/drive")

import sys
from pathlib import Path

DRIVE_ROOT = Path("/content/drive/MyDrive/store-search-ai")
PROJECT_DIR = DRIVE_ROOT / "project"          # VSCode 프로젝트를 그대로 올려둔 곳
RUN_DIR = DRIVE_ROOT / "runs" / "model_eval"   # 여기를 결과로 다시 로컬로 가져간다

RUN_DIR.mkdir(parents=True, exist_ok=True)

# VSCode 프로젝트의 src/를 그대로 import 경로에 추가 — 코드를 복사하지 않고 재사용한다.
sys.path.insert(0, str(PROJECT_DIR / "src"))

from store_search_ai.models.sentence_transformer_encoder import SentenceTransformerEncoder
from store_search_ai.retrieval.exact_search import ExactCosineSearch
from store_search_ai.pipeline.common import load_config

print("PROJECT_DIR:", PROJECT_DIR)
print("RUN_DIR:", RUN_DIR)

"""## 데이터 로드

VSCode 프로젝트와 완전히 동일한 파일(같은 corpus, 같은 queries.csv)을 그대로 쓴다 —
따로 안 옮기고 실수로 다른 버전을 인코딩하는 일을 방지하기 위함이다.
"""

import pandas as pd

CORPUS_PATH = PROJECT_DIR / "data" / "corpus" / "store_corpus_v002.parquet"
QUERY_PATH = PROJECT_DIR / "benchmark" / "storesearch_ko_v1" / "queries.csv"

corpus = pd.read_parquet(CORPUS_PATH)
queries = pd.read_csv(QUERY_PATH, encoding="utf-8-sig")

print("corpus:", corpus.shape)
print("queries:", queries.shape)

assert corpus["doc_id"].notna().all()
assert corpus["doc_id"].nunique() == len(corpus)
print("Unique docs:", corpus["doc_id"].nunique())

TEXT_COLUMNS = {
    "t1_minimal": "search_text_t1_minimal",
    "t2_market": "search_text_t2_market",
    "t3_market_type": "search_text_t3_market_type",
}

# ==========================================================
# 여기 세 개만 바꾸면 된다: 어떤 split을 평가할지, 어떤 template들을 시도할지,
# (val은 모델 선정용, test는 최종 후보 확정 후 딱 한 번만 — docs/PIPELINE.md 참고)
# corpus 인코딩(214k 문서)이 template마다 매번 다시 도는 게 가장 비싼 부분이라,
# 처음엔 T1(공식 document representation, docs/PIPELINE.md 1절)만 빠르게 돌려보고
# 필요할 때만 T2/T3를 추가하는 걸 권장한다.
# ==========================================================
SPLIT = "val"
TEMPLATES = ["t1_minimal"]  # 필요해지면 "t2_market", "t3_market_type" 추가

split_queries = queries[
    (queries["split"] == SPLIT) & (queries["status"] == "active")
].reset_index(drop=True)

print(f"{SPLIT} queries:", len(split_queries))
print(split_queries[["query_id", "query_family", "query_type", "query"]].head(10))

"""## 모델 목록 (configs/models/*.yaml에서 그대로 읽는다)

기본은 `configs/models/*.yaml` 전부를 순회한다(정식 비교용 — 이 리스트를 영구히 바꾸려면
이 셀이 아니라 yaml 파일 자체를 추가/삭제할 것, docs/EXTENDING_DATA.md 방식과 동일한 원칙).

**일단 1~2개 모델로만 빠르게 찍어보고 싶으면** `MODEL_CONFIG_NAMES`에 파일명을 적는다 —
corpus 인코딩이 모델마다 다시 도는 게 비싼 부분이라, 처음엔 이렇게 좁혀서 배관/성능을
확인한 뒤 나머지 모델로 넓히는 걸 권장한다.
"""

MODEL_CONFIG_DIR = PROJECT_DIR / "configs" / "models"

MODEL_CONFIG_NAMES = None  # 예: ["bge_m3.yaml", "qwen3_0_6b.yaml"] — None이면 전체

if MODEL_CONFIG_NAMES:
    model_config_paths = [MODEL_CONFIG_DIR / name for name in MODEL_CONFIG_NAMES]
    missing = [p for p in model_config_paths if not p.exists()]
    assert not missing, f"찾을 수 없는 모델 설정: {missing}"
else:
    model_config_paths = sorted(MODEL_CONFIG_DIR.glob("*.yaml"))

print("발견된 모델 설정:")
for p in model_config_paths:
    print(" -", p.name)

"""## 인코딩 → 검색 → run.csv (모델별로 순회)

VSCode의 `SentenceTransformerEncoder`, `ExactCosineSearch`를 그대로 쓴다 —
retrieval 로직을 Colab에 다시 구현하지 않는다.
"""

import gc

FINETUNE_RUN_DIR = DRIVE_ROOT / "runs" / "finetune"

# 이미 run.csv가 있는 모델은 건너뛴다 — Colab 연결이 끊겨 다시 실행할 때 끝난 모델을 또 인코딩하지 않게.
# 같은 tag로 다시 돌리고 싶으면 False로 하거나 Drive의 그 run 폴더를 지운다.
SKIP_EXISTING = True


def resolve_config(model_config_path):
    config = load_config(model_config_path)
    # fine-tuned 모델의 eval_config.yaml은 로컬 경로(models/<TAG>)를 가리킨다 — Colab에서는 같은 모델이
    # Drive runs/finetune/<TAG>/에 있으므로 그쪽으로 바꿔서 읽는다(yaml을 Colab용으로 따로 고칠 필요 없음).
    if str(config["model_id"]).startswith("models/"):
        config = {**config, "model_id": str(FINETUNE_RUN_DIR / Path(config["model_id"]).name)}
    return config


def corpus_key(config):
    """문서 임베딩을 좌우하는 값 — 이게 같으면 query prompt만 다른 변형끼리 문서 임베딩을 재사용한다."""

    return (config["model_id"], config.get("torch_dtype"), config.get("target_dimension"),
            config.get("normalize_embeddings", True))


# 같은 모델(문서 임베딩이 같은 설정)끼리 붙여서 돌린다 → 모델 로드·문서 인코딩(가장 비싼 부분)을 한 번만.
configs = sorted((resolve_config(p) for p in model_config_paths), key=lambda c: (str(corpus_key(c)), c["name"]))

query_texts = split_queries["query"].astype(str).tolist()
doc_ids = corpus["doc_id"].tolist()
encoder, encoder_key, doc_cache = None, None, {}

for config in configs:
    tag = config["name"]
    output_dir = RUN_DIR / tag
    pending = [t for t in TEMPLATES if not (SKIP_EXISTING and (output_dir / f"run_{t}_{SPLIT}.csv").exists())]
    if not pending:
        print(f"\n===== {tag}: 이미 완료 — 건너뜀 =====")
        continue
    print(f"\n===== {tag} ({config['model_id']}) =====")

    key = corpus_key(config)
    if key != encoder_key:
        del encoder
        doc_cache = {}
        gc.collect()
        torch.cuda.empty_cache()
        encoder, encoder_key = SentenceTransformerEncoder(config), key
    encoder.config = config  # 같은 모델이면 가중치는 재사용하고 query prompt 등 설정만 바꾼다

    query_embeddings = encoder.encode_queries(query_texts)
    output_dir.mkdir(parents=True, exist_ok=True)

    for template in pending:
        if template not in doc_cache:
            documents = corpus[TEXT_COLUMNS[template]].fillna("").astype(str).tolist()
            doc_cache[template] = encoder.encode_corpus(documents)
        else:
            print(f"  [{template}] 문서 임베딩 재사용(같은 모델의 다른 prompt 변형)")

        searcher = ExactCosineSearch(corpus_embeddings=doc_cache[template], doc_ids=doc_ids)
        run = searcher.search(
            query_embeddings=query_embeddings,
            query_ids=split_queries["query_id"].tolist(),
            top_k=100,
            system=f"{tag}_{template}",
        )
        run_path = output_dir / f"run_{template}_{SPLIT}.csv"
        run.to_csv(run_path, index=False, encoding="utf-8-sig")
        print(f"  [{template}] saved: {run_path} ({len(run)} rows)")

del encoder, doc_cache
gc.collect()
torch.cuda.empty_cache()

print("\n모든 모델 완료. RUN_DIR을 통째로 로컬 results/model_eval/ 에 복사하세요:")
print(RUN_DIR)

"""## query prompt 실험은 yaml로

예전에는 여기에 custom instruction을 즉흥적으로 시험하는 셀이 있었다. 지금은 prompt 문자열을 yaml의
`query_prompt`에 적은 변형 yaml을 두는 방식으로 바꿨다(예: `configs/models/qwen3_0_6b_store.yaml`) —
기록이 남고, 위 루프에서 같은 모델의 문서 임베딩을 재사용하므로 추가 비용이 query 인코딩뿐이며, 좋은 쪽을
그대로 학습(`colab/run_finetune_qwen3.py`의 MODEL_CONFIG)에 쓸 수 있다.
"""
