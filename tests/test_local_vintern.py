"""Vintern adapter helpers that can be tested without a GPU or the model."""

from __future__ import annotations

from hannom.ocr.local_vintern import _drop_return_dict


class _FakeLanguageModel:
    def __init__(self):
        self.calls = []

    def generate(self, *args, **kwargs):
        self.calls.append(kwargs)
        return "tokens"


class _FakeChatModel:
    def __init__(self):
        self.language_model = _FakeLanguageModel()


def test_return_dict_is_dropped_before_language_model_generate():
    model = _FakeChatModel()
    inner = model.language_model
    _drop_return_dict(model)
    _drop_return_dict(model)  # idempotent: wrapping twice must not stack
    out = model.language_model.generate(inputs_embeds="x", return_dict=None, use_cache=True)
    assert out == "tokens"
    assert inner.calls == [{"inputs_embeds": "x", "use_cache": True}]


def test_models_without_language_model_are_left_alone():
    class Plain:
        pass

    plain = Plain()
    _drop_return_dict(plain)
    assert not hasattr(plain, "language_model")
