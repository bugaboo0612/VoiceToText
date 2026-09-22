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


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Скинь в телеграм.", "Скинь в Telegram."),
        ("Открой гитхаб и запусти клод код.", "Открой GitHub и запусти Claude Code."),
        ("Таблица в эксель, письмо в ворд.", "Таблица в Excel, письмо в Word."),
        ("Выгрузи из ревит в автокад.", "Выгрузи из Revit в AutoCAD."),
        ("Спроси у чат джипити.", "Спроси у ChatGPT."),
        ("Загрузи на гугл диск.", "Загрузи на Google Drive."),
        ("Позвони по вотсап.", "Позвони по WhatsApp."),
        ("Напиши на питон.", "Напиши на Python."),
        ("Проверь эй пи ай.", "Проверь API."),
        ("Проверь эй-пи-ай.", "Проверь API."),
    ],
)
def test_service_names_from_base_dictionary(raw, expected):
    # словарь ловит начальную форму; формы с окончаниями исправляет ИИ-редактор
    assert editor.apply_dictionary(raw) == expected


def test_dictionary_does_not_touch_similar_russian_words():
    text = "Получил телеграмму, поставь курсор в конец строки, погугли это, зумер шумит."
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


# --- защита второго запроса: он имеет право менять только знаки препинания ---

@pytest.mark.parametrize(
    "before, after",
    [
        # поделили на предложения - слова те же
        ("Подрядчик привёз кабель, я его развернул.", "Подрядчик привёз кабель. Я его развернул."),
        # союз в начале нового предложения разрешено убрать
        ("У соседа собака лает, и решётка погнулась.", "У соседа собака лает. Решётка погнулась."),
        ("Открой файл, а таблицу пришли мне.", "Открой файл. Таблицу пришли мне."),
        # ничего не изменилось
        ("Раздел АР-2 готов.", "Раздел АР-2 готов."),
        # точка в конце и заглавная буква - это тоже только знаки
        ("документы готовы, я их отправил", "Документы готовы. Я их отправил."),
        # адрес почты не должен развалиться на части
        ("Скинь смету на ivan.petrov@gmail.com, я жду.", "Скинь смету на ivan.petrov@gmail.com. Я жду."),
    ],
)
def test_only_punctuation_changed_allows(before, after):
    assert editor.only_punctuation_changed(before, after)


@pytest.mark.parametrize(
    "before, after",
    [
        # слово подменено
        ("Документы готовы, затем позвоню.", "Документы готовы. Тогда позвоню."),
        # слово выброшено
        ("В разделе АР-2 поменяли планировку, поэтому смету пересчитать.",
         "В разделе АР-2 поменяли планировку. Смету пересчитать."),
        # слова добавлены
        ("Указать номер договора и сумму долга.", "Указать номер договора. Нужно указать сумму долга."),
        # число изменилось
        ("Нужно 25 кубов бетона.", "Нужно 20 кубов бетона."),
        # модель ответила вместо редактуры
        ("Напиши функцию, которая сортирует список.", "def sort(items): return sorted(items)"),
    ],
)
def test_only_punctuation_changed_rejects(before, after):
    assert not editor.only_punctuation_changed(before, after)
