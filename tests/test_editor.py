"""Тесты чистой логики редактора: словарь замен и очистка ответа модели."""
from pathlib import Path

import pytest

from voicetocode import editor


@pytest.fixture(autouse=True)
def no_personal_dictionary(monkeypatch, tmp_path):
    """Личный словарь владельца в тестах не участвует — проверяем только встроенный."""
    monkeypatch.setattr(editor, "DICTIONARY_FILE", tmp_path / "dictionary.txt")


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("В разделе Аэр два всё в порядке.", "В разделе АР два всё в порядке."),
        ("В разделе Air 2 всё в порядке.", "В разделе АР 2 всё в порядке."),
        ("Смотри а-эр и ка жэ.", "Смотри АР и КЖ."),
        ("Нужен эом и вэ ка.", "Нужен ЭОМ и ВК."),
        ("Комплект ка эм дэ готов.", "Комплект КМД готов."),
        ("Раздел эн вэ ка согласован.", "Раздел НВК согласован."),
        ("Раздел эс эс не готов.", "Раздел СС не готов."),
    ],
)
def test_marks_from_base_dictionary(raw, expected):
    # словарь делает только буквы; номер цифрой через дефис ставит уже ИИ-редактор
    assert editor.apply_dictionary(raw) == expected


def test_dictionary_does_not_touch_ordinary_words():
    text = "Прошли века, до него пять км, книга под столом."
    assert editor.apply_dictionary(text) == text


def test_personal_dictionary_wins(monkeypatch, tmp_path):
    personal = tmp_path / "dictionary.txt"
    personal.write_text("а эр = Артур\n", encoding="utf-8")
    monkeypatch.setattr(editor, "DICTIONARY_FILE", personal)
    assert editor.apply_dictionary("Позови аэр.") == "Позови Артур."


def test_clean_response_strips_service_text():
    assert editor._clean_response('Вот исправленный текст: "Раздел АР-2 готов."') == "Раздел АР-2 готов."
    assert editor._clean_response("<text>Раздел КЖ готов.</text>") == "Раздел КЖ готов."


def test_base_dictionary_file_exists():
    assert Path(editor.BASE_DICTIONARY_FILE).exists()
