"""임베딩 서버(요구사항 IR-10, docs/ARCHITECTURE.md ③).

문장 목록을 받아 1024차원 float32 벡터(L2 정규화)를 돌려준다. 검색어와 가게 문장에 같은 모델·같은 처리를 쓴다
(평가 설정 configs/models/bge_m3_ft_mj_20261014_0743.yaml: query prompt 없음, normalize_embeddings = true).

- POST /embed  {"texts": ["둔산동 치킨"]} → {"model": ..., "dimension": 1024, "vectors": [[...]], "elapsedMs": ...}
- GET  /health → 모델이 올라왔으면 200
"""

from __future__ import annotations

import os
import time

import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

MODEL_PATH = os.environ.get("MODEL_PATH", "/models/current")
MODEL_NAME = os.environ.get("MODEL_NAME", "bge_m3_ft_mj_20261014_0743")
MAX_BATCH = int(os.environ.get("MAX_BATCH", "64"))
MAX_CHARS = 300  # 스냅샷 doc_text 최대 길이(varchar(300))와 맞춤

torch.set_num_threads(int(os.environ.get("TORCH_NUM_THREADS", "4")))

app = FastAPI(title="store-search embedding", version="0.1.0")
_model: SentenceTransformer | None = None


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=MAX_BATCH)


class EmbedResponse(BaseModel):
    model: str
    dimension: int
    vectors: list[list[float]]
    elapsedMs: float


@app.on_event("startup")
def load_model() -> None:
    global _model
    # CPU fp32(요구사항 1-3). 평가 때와 같은 모델 폴더를 읽는다
    _model = SentenceTransformer(MODEL_PATH, device="cpu")
    _model.encode(["준비"], normalize_embeddings=True)  # 첫 요청이 느리지 않게 미리 한 번


@app.get("/health")
def health() -> dict:
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return {"status": "ok", "model": MODEL_NAME, "dimension": _model.get_sentence_embedding_dimension()}


@app.post("/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if _model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    texts = [t.strip()[:MAX_CHARS] for t in req.texts]
    if any(not t for t in texts):
        raise HTTPException(status_code=400, detail="empty text")
    started = time.perf_counter()
    with torch.no_grad():
        vectors = _model.encode(texts, batch_size=len(texts), normalize_embeddings=True,
                                convert_to_numpy=True, show_progress_bar=False)
    elapsed = (time.perf_counter() - started) * 1000
    return EmbedResponse(model=MODEL_NAME, dimension=int(vectors.shape[1]),
                         vectors=vectors.astype("float32").tolist(), elapsedMs=round(elapsed, 1))
