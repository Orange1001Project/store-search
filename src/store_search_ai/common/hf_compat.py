"""transformers 4.x/5.x, sentence-transformers 3.x~5.x 양쪽에서 같은 코드가 돌게 하는 작은 호환 함수들.

Colab 기본 런타임은 HF 라이브러리를 자주 올린다(2026-10 기준 transformers 5.18, sentence-transformers 5.7, Python 3.13).
예전에는 노트북에서 옛 버전(transformers 4.51, sentence-transformers 3.4)을 강제로 설치했는데, 그러면 Colab에 깔린
huggingface_hub·fsspec까지 내려가 gradio·diffusers·gcsfs와 충돌하고, Colab이 업데이트될수록 더 어긋난다.
그래서 지금은 **Colab에 깔린 버전을 그대로 쓰고**, 버전마다 바뀐 API만 여기서 맞춘다. 실제로 쓴 버전은 학습·평가 기록
(manifest `environment`, 평가 json `library_versions`)에 남는다.

버전 차이(이 파일이 흡수하는 것):
- transformers 5: `from_pretrained(torch_dtype=...)` → `dtype=...` (옛 이름은 deprecated 경고)
- transformers 5: `TrainingArguments(warmup_ratio=...)` 삭제 → `warmup_steps`에 0~1 비율을 넣는다
- sentence-transformers 5: Transformer 모듈의 `auto_model`이 읽기 전용 property(실체는 `.model`)
- sentence-transformers 5: `sentence_transformers.training_args`·`losses` 위치 이동(옛 경로는 deprecated 경고)
"""

from __future__ import annotations

import dataclasses
from importlib import metadata

MINIMUM_VERSIONS = {
    "transformers": (4, 51),           # Qwen3 지원 시작
    "sentence-transformers": (3, 3),   # Trainer prompts 인자
    "peft": (0, 13),
    "datasets": (2, 19),
    "accelerate": (0, 26),
}
TESTED_MAJOR = {"transformers": 5, "sentence-transformers": 5}
"""여기까지의 메이저 버전에서 API 차이를 확인했다. Colab이 이보다 새 메이저 버전으로 올라가면 경고만 낸다(smoke test 먼저)."""
LIBRARIES = ["torch", "transformers", "sentence-transformers", "peft", "datasets", "accelerate",
             "huggingface-hub", "ir-measures", "pytrec-eval-terrier"]


def version_tuple(package: str) -> tuple[int, ...] | None:
    try:
        raw = metadata.version(package)
    except metadata.PackageNotFoundError:
        return None
    parts = []
    for piece in raw.split("+")[0].split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def library_versions(packages: list[str] | None = None) -> dict[str, str | None]:
    versions = {}
    for name in packages or LIBRARIES:
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def check_environment(require_eval: bool = True) -> dict[str, str | None]:
    """노트북 시작 시 호출: 버전을 출력하고, 최소 버전보다 낮거나 없는 패키지가 있으면 바로 알려 준다."""

    versions = library_versions()
    problems = []
    for package, minimum in MINIMUM_VERSIONS.items():
        found = version_tuple(package)
        if found is None:
            problems.append(f"{package} 없음 — !pip install {package}")
        elif found[: len(minimum)] < minimum:
            problems.append(f"{package} {versions[package]} < {'.'.join(map(str, minimum))}")
    if require_eval:
        for package in ("ir-measures", "pytrec-eval-terrier"):
            if versions.get(package) is None:
                problems.append(f"{package} 없음 — 설치 셀을 다시 실행")
    for package, major in TESTED_MAJOR.items():
        found = version_tuple(package)
        if found and found[0] > major:
            print(f"[경고] {package} {versions.get(package)}: 확인된 적 없는 메이저 버전 — colab/smoke_test_finetune.ipynb로 먼저 확인하세요")
    print("[환경] " + ", ".join(f"{k}={v}" for k, v in versions.items()))
    if problems:
        raise RuntimeError("Colab 환경 문제: " + "; ".join(problems))
    return versions


def dtype_kwargs(dtype) -> dict:
    """`from_pretrained`/`SentenceTransformer(model_kwargs=...)`에 넘길 dtype 인자(transformers 버전에 맞는 이름)."""

    found = version_tuple("transformers") or (0,)
    return {"dtype": dtype} if found >= (4, 56) else {"torch_dtype": dtype}


def set_transformer_model(module, model) -> None:
    """sentence-transformers Transformer 모듈의 내부 HF 모델을 교체한다(LoRA 래핑·merge 후).

    3.x/4.x는 `auto_model`이 일반 속성, 5.x는 읽기 전용 property(실체는 `.model`)다.
    """

    attribute = getattr(type(module), "auto_model", None)
    if isinstance(attribute, property) and attribute.fset is None:
        module.model = model
    else:
        module.auto_model = model


def warmup_kwargs(training_args_class, ratio: float) -> dict:
    """학습 인자 클래스가 받는 warmup 인자. transformers 5는 `warmup_ratio`가 없고 `warmup_steps`에 비율을 넣는다."""

    fields = {field.name for field in dataclasses.fields(training_args_class)}
    return {"warmup_ratio": ratio} if "warmup_ratio" in fields else {"warmup_steps": ratio}


def batch_samplers():
    try:
        from sentence_transformers.base.sampler import BatchSamplers
    except ImportError:  # sentence-transformers < 5
        from sentence_transformers.training_args import BatchSamplers
    return BatchSamplers


def losses_module():
    """sentence-transformers 5는 losses가 sentence_transformers.sentence_transformer.losses로 이동(옛 경로는 경고)."""

    try:
        from sentence_transformers.sentence_transformer import losses
    except ImportError:  # sentence-transformers < 5
        from sentence_transformers import losses
    return losses


def embedding_dimension(model) -> int:
    method = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return method()
