"""`sentence-transformers`로 로드 가능한 임베딩 모델을 위한 BaseEncoder 구현.

원본 프로젝트의 `embedding/encoder.py`(EmbeddingEncoder)를 정리한 버전이다. 동작은 동일하다:
- L2 normalize 여부와 target_dimension(Matryoshka 축소) 지원
- query 인코딩에만 `query_prompt_name`(sentence-transformers의 `prompt_name`) 적용

`configs/models/*.yaml` 하나가 인코더 하나의 설정과 1:1로 대응한다.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from store_search_ai.models.base import BaseEncoder
from store_search_ai.pipeline.common import load_config


class SentenceTransformerEncoder(BaseEncoder):
    def __init__(self, config: dict):
        # sentence-transformers/torch는 무거운 선택적 의존성이라 여기서만 import한다
        # (pip install -e ".[embedding]" 했을 때만 필요).
        import torch
        from sentence_transformers import SentenceTransformer

        self._torch = torch
        self.config = config
        self.model = SentenceTransformer(config["model_id"])

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SentenceTransformerEncoder":
        return cls(load_config(path))

    @property
    def name(self) -> str:
        return self.config["name"]

    def _postprocess(self, embeddings: np.ndarray) -> np.ndarray:
        dim = self.config.get("target_dimension")
        if dim is not None:
            embeddings = embeddings[:, :dim]
        if self.config.get("normalize_embeddings", True):
            norms = np.clip(
                np.linalg.norm(embeddings, axis=1, keepdims=True),
                1e-12,
                None,
            )
            embeddings = embeddings / norms
        return embeddings.astype("float32")

    def encode_corpus(self, texts: list[str]) -> np.ndarray:
        with self._torch.no_grad():
            embeddings = self.model.encode(
                texts,
                batch_size=self.config.get("batch_size", 32),
                normalize_embeddings=False,
                show_progress_bar=True,
                convert_to_numpy=True,
            )
        return self._postprocess(embeddings)

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        kwargs = {
            "batch_size": self.config.get("batch_size", 32),
            "normalize_embeddings": False,
            "show_progress_bar": True,
            "convert_to_numpy": True,
        }
        prompt_name = self.config.get("query_prompt_name")
        if prompt_name:
            kwargs["prompt_name"] = prompt_name
        with self._torch.no_grad():
            embeddings = self.model.encode(texts, **kwargs)
        return self._postprocess(embeddings)
