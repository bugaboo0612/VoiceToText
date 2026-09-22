"""Тесты чистой логики проверки обновлений: разбор названий моделей и текст отчёта.

Сеть здесь не используется — только разбор строк.
"""
import pytest

from voicetocode import updates


@pytest.mark.parametrize(
    "model, expected",
    [
        ("qwen3:8b", ("library/qwen3", "8b")),
        ("qwen3", ("library/qwen3", "latest")),
        ("gemma3:12b-it-qat", ("library/gemma3", "12b-it-qat")),
        ("ruadapt/qwen3:8b", ("ruadapt/qwen3", "8b")),
        ("hf.co/user/model:q4", None),  # модель не с ollama.com — проверять нечем
        ("", None),
    ],
)
def test_split_ollama_name(model, expected):
    assert updates.split_ollama_name(model) == expected


@pytest.mark.parametrize(
    "model, expected",
    [("qwen3:8b", "qwen3:8b"), ("qwen3", "qwen3:latest")],
)
def test_with_tag(model, expected):
    assert updates._with_tag(model) == expected


def test_model_title_short():
    """В отчёте показываем короткое название модели, без пояснения в скобках."""
    assert updates._model_title("nemo-parakeet-tdt-0.6b-v3") == "Модель распознавания (Parakeet)"


def test_status_line():
    status = updates.ModelStatus(
        updates.KIND_OLLAMA, "qwen3:8b", "Модель редактуры (qwen3:8b)", updates.UP_TO_DATE, "установлена последняя версия"
    )
    assert status.line == "Модель редактуры (qwen3:8b): установлена последняя версия"
