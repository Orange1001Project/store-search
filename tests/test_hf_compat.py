import dataclasses

import pytest

from store_search_ai.common import hf_compat


class _ST3Transformer:
    """sentence-transformers 3.x/4.x: auto_model이 일반 속성."""

    def __init__(self):
        self.auto_model = "base"


class _ST5Transformer:
    """sentence-transformers 5.x: auto_model은 읽기 전용 property, 실체는 .model."""

    def __init__(self):
        self.model = "base"

    @property
    def auto_model(self):
        return self.model


@pytest.mark.parametrize("cls", [_ST3Transformer, _ST5Transformer])
def test_set_transformer_model_works_for_both_generations(cls):
    module = cls()
    hf_compat.set_transformer_model(module, "peft-wrapped")
    assert module.auto_model == "peft-wrapped"


def test_plain_assignment_fails_on_st5_which_is_why_the_helper_exists():
    with pytest.raises(AttributeError):
        _ST5Transformer().auto_model = "x"


@dataclasses.dataclass
class _ArgsV4:
    warmup_ratio: float = 0.0
    warmup_steps: int = 0


@dataclasses.dataclass
class _ArgsV5:
    warmup_steps: float = 0


def test_warmup_kwargs_picks_the_supported_field():
    assert hf_compat.warmup_kwargs(_ArgsV4, 0.1) == {"warmup_ratio": 0.1}
    assert hf_compat.warmup_kwargs(_ArgsV5, 0.1) == {"warmup_steps": 0.1}


@pytest.mark.parametrize("version,key", [((4, 51, 3), "torch_dtype"), ((4, 56, 0), "dtype"), ((5, 18, 0), "dtype")])
def test_dtype_kwargs_uses_the_name_of_the_installed_transformers(monkeypatch, version, key):
    monkeypatch.setattr(hf_compat, "version_tuple", lambda package: version)
    assert hf_compat.dtype_kwargs("float16") == {key: "float16"}


def test_embedding_dimension_prefers_new_method_and_falls_back():
    class New:
        def get_embedding_dimension(self):
            return 1024

        def get_sentence_embedding_dimension(self):  # 5.x에서는 deprecated
            raise AssertionError("old method should not be called")

    class Old:
        def get_sentence_embedding_dimension(self):
            return 768

    assert hf_compat.embedding_dimension(New()) == 1024
    assert hf_compat.embedding_dimension(Old()) == 768


def test_check_environment_reports_missing_packages(monkeypatch):
    monkeypatch.setattr(hf_compat, "version_tuple", lambda package: None if package == "peft" else (99,))
    monkeypatch.setattr(hf_compat, "library_versions", lambda packages=None: {"peft": None, "ir-measures": "0.4.3",
                                                                                "pytrec-eval-terrier": "0.5.10"})
    with pytest.raises(RuntimeError, match="peft 없음"):
        hf_compat.check_environment()
