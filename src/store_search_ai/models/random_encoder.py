"""네트워크·GPU 없이 retrieval/evaluation 코드 경로를 검증하기 위한 가짜 인코더.

실제 서비스에는 쓰지 않는다. `SentenceTransformerEncoder`와 동일한 `BaseEncoder` 계약을
따르므로, `scripts/14_run_model_eval.py`를 이 인코더로 실행하면 실제 모델 다운로드 없이
"corpus 인코딩 → exact search → run.csv → 공식 evaluator" 전체 배관이 올바르게 연결돼
있는지 확인할 수 있다 (숫자 자체는 무의미하다 — 관련성과 무관한 랜덤 벡터이기 때문).
"""

from __future__ import annotations

import hashlib

import numpy as np

from store_search_ai.models.base import BaseEncoder


class RandomEncoder(BaseEncoder):
    def __init__(self, dim: int = 32, seed: int = 20260831):
        self.dim = dim
        self.seed = seed

    @property
    def name(self) -> str:
        return "random_encoder_smoke_test"

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.empty((len(texts), self.dim), dtype="float32")
        for i, text in enumerate(texts):
            # 텍스트 해시로 시드를 고정해서, 같은 문자열은 항상 같은 벡터를 받게 한다
            # (완전 무작위면 재실행할 때마다 run.csv가 바뀌어 디버깅이 어려워짐).
            text_seed = int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.default_rng(self.seed ^ text_seed)
            vectors[i] = rng.normal(size=self.dim)
        norms = np.clip(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12, None)
        return (vectors / norms).astype("float32")

    def encode_corpus(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)
