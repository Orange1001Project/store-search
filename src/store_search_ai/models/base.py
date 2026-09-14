"""임베딩 인코더 공통 인터페이스.

BEIR(`beir.retrieval.models`)이 채택한 패턴을 그대로 따른다: 검색에 관여하는 모든 컴포넌트가
"인코더는 텍스트를 벡터로 바꾸는 것만 안다"는 계약 하나만 지키면, 어떤 모델을 꽂아도
retrieval/evaluation 코드는 손대지 않아도 된다.

corpus와 query를 별도 메서드로 분리한 이유: 많은 임베딩 모델(BGE-M3, Qwen3-Embedding,
multilingual-e5 등)이 query 쪽에만 instruction/prompt를 붙이도록 설계되어 있어서
(`configs/models/*.yaml`의 `query_prompt_name` 참고), 두 입력을 같은 경로로 취급하면 안 된다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class BaseEncoder(ABC):
    """모든 임베딩 인코더가 구현해야 하는 최소 계약."""

    @abstractmethod
    def encode_corpus(self, texts: list[str]) -> np.ndarray:
        """corpus 문서 텍스트 리스트 → (N, dim) float32 배열."""

    @abstractmethod
    def encode_queries(self, texts: list[str]) -> np.ndarray:
        """query 텍스트 리스트 → (N, dim) float32 배열."""

    @property
    @abstractmethod
    def name(self) -> str:
        """run.csv의 system 컬럼에 기록될 모델 식별자."""
