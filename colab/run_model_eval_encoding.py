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
    'pip -q install -U "transformers>=4.51.0" sentence-transformers accelerate'
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


def run_one_model(model_config_path, templates, split_queries, corpus, split):
    config = load_config(model_config_path)
    tag = config["name"]
    print(f"\n===== {tag} ({config['model_id']}) =====")

    encoder = SentenceTransformerEncoder(config)

    query_texts = split_queries["query"].astype(str).tolist()
    query_embeddings = encoder.encode_queries(query_texts)

    output_dir = RUN_DIR / tag
    output_dir.mkdir(parents=True, exist_ok=True)

    for template in templates:
        text_col = TEXT_COLUMNS[template]
        documents = corpus[text_col].fillna("").astype(str).tolist()

        doc_embeddings = encoder.encode_corpus(documents)

        searcher = ExactCosineSearch(
            corpus_embeddings=doc_embeddings,
            doc_ids=corpus["doc_id"].tolist(),
        )
        run = searcher.search(
            query_embeddings=query_embeddings,
            query_ids=split_queries["query_id"].tolist(),
            top_k=100,
            system=f"{tag}_{template}",
        )

        run_path = output_dir / f"run_{template}_{split}.csv"
        run.to_csv(run_path, index=False, encoding="utf-8-sig")
        print(f"  [{template}] saved: {run_path} ({len(run)} rows)")

        del doc_embeddings
        gc.collect()

    del encoder
    gc.collect()
    torch.cuda.empty_cache()


for model_config_path in model_config_paths:
    run_one_model(model_config_path, TEMPLATES, split_queries, corpus, SPLIT)

print("\n모든 모델 완료. RUN_DIR을 통째로 로컬 results/model_eval/ 에 복사하세요:")
print(RUN_DIR)

"""## (선택) query prompt 실험 — 모델 기본 prompt vs custom instruction

원본 노트북에서 하시던 "native vs store instruction" 비교입니다. 이건 `configs/models/*.yaml`의
표준 루프와 별개로, 궁금한 모델 하나에 대해서만 즉흥적으로 돌려보는 실험용 셀입니다.
결과 run도 스키마·저장 위치는 동일하게 맞춰서, `results/model_eval/<tag>__store_prompt/`처럼
별도 tag를 붙여 VSCode에서 나머지와 동일하게 채점할 수 있게 했습니다.
"""

CUSTOM_PROMPT_MODEL_CONFIG = MODEL_CONFIG_DIR / "qwen3_0_6b.yaml"  # 실험하고 싶은 모델로 교체
STORE_QUERY_PROMPT = (
    "Instruct: Given a Korean local-store search query, "
    "retrieve stores that satisfy the user's shopping, "
    "dining, or service intent\nQuery:"
)

config = load_config(CUSTOM_PROMPT_MODEL_CONFIG)
encoder = SentenceTransformerEncoder(config)

# encode_queries()는 config의 query_prompt_name을 쓰므로, custom prompt를 쓰려면
# sentence-transformers 모델을 직접 호출한다 (BaseEncoder 계약 밖의 1회성 실험이라 허용).
query_texts = split_queries["query"].astype(str).tolist()
custom_query_embeddings = encoder.model.encode(
    query_texts,
    prompt=STORE_QUERY_PROMPT,
    batch_size=config.get("batch_size", 32),
    normalize_embeddings=True,
    convert_to_numpy=True,
    show_progress_bar=True,
)

doc_embeddings = encoder.encode_corpus(
    corpus[TEXT_COLUMNS["t1_minimal"]].fillna("").astype(str).tolist()
)
searcher = ExactCosineSearch(doc_embeddings, corpus["doc_id"].tolist())
run = searcher.search(
    query_embeddings=custom_query_embeddings,
    query_ids=split_queries["query_id"].tolist(),
    top_k=100,
    system=f"{config['name']}_t1_store_prompt",
)

output_dir = RUN_DIR / f"{config['name']}__store_prompt"
output_dir.mkdir(parents=True, exist_ok=True)
run_path = output_dir / f"run_t1_{SPLIT}.csv"
run.to_csv(run_path, index=False, encoding="utf-8-sig")
print("saved:", run_path)

del encoder, doc_embeddings
gc.collect()
torch.cuda.empty_cache()
