"""Редактор: словарь замен, чистка текста и смена стиля через локальную модель в Ollama."""
import logging
import re
from pathlib import Path

import requests

from voicetocode import settings

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"  # не "localhost": на Windows его резолвинг иногда занимает 2+ секунды
DEFAULT_MODEL = "qwen3:8b"
TIMEOUT_SEC = 20
KEEP_ALIVE = "30m"
TEMPERATURE = 0.2

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

# Встроенный словарь (марки разделов документации) лежит в папке проекта, личный — в %APPDATA%
BASE_DICTIONARY_FILE = Path(__file__).resolve().parent.parent / "dictionary_base.txt"
DICTIONARY_FILE = settings.DATA_DIR / "dictionary.txt"
DICTIONARY_TEMPLATE = (
    "# Словарь замен VoiceToText.\n"
    "# Одна строка - одна замена. Формат: как расслышала модель = как надо написать\n"
    "# Строки, начинающиеся с #, - это комментарии, они игнорируются.\n"
    "#\n"
    "# Пример (уберите # в начале строки, чтобы замена заработала):\n"
    "# клод код = Claude Code\n"
)

STYLE_RAW = "raw"  # без обработки — Ollama не вызывается
STYLE_FILES = {
    "normal": "normal.txt",
    "polite": "polite.txt",
    "professional": "professional.txt",
}

_PREFIX_PATTERNS = [
    r"^вот\s+(?:исправленный|отредактированный|итоговый|очищенный)\s+текст\s*:?\s*",
    r"^исправленный\s+текст\s*:?\s*",
    r"^результат\s*:?\s*",
]


def ensure_dictionary_file() -> None:
    """Создаёт пустой словарь с пояснениями, если его ещё нет."""
    settings.ensure_data_dir()
    if not DICTIONARY_FILE.exists():
        try:
            DICTIONARY_FILE.write_text(DICTIONARY_TEMPLATE, encoding="utf-8")
        except OSError:
            logger.warning("Не удалось создать файл словаря", exc_info=True)


def _read_pairs(path: Path) -> list[tuple[str, str]]:
    pairs = []
    if not path.exists():
        return pairs
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        logger.warning("Не удалось прочитать словарь замен: %s", path, exc_info=True)
        return pairs

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            pairs.append((key, value))
    return pairs


def _load_dictionary() -> list[tuple[str, str]]:
    """Сначала личные замены владельца, потом встроенные — так личные имеют приоритет."""
    return _read_pairs(DICTIONARY_FILE) + _read_pairs(BASE_DICTIONARY_FILE)


def _build_pattern(key: str) -> re.Pattern:
    """Пробелы и дефисы внутри ключа не важны: "а эр" ловит и "аэр", и "а-эр"."""
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", key) if part]
    return re.compile(r"(?<!\w)" + r"[\s\-]*".join(parts) + r"(?!\w)", re.IGNORECASE)


def apply_dictionary(text: str) -> str:
    """Заменяет слова/фразы по словарю замен (без учёта регистра, по границам слов)."""
    for key, value in _load_dictionary():
        text = _build_pattern(key).sub(value.replace("\\", "\\\\"), text)
    return text


def _read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _build_system_prompt(style: str) -> str:
    """Инструкция для первого запроса: чистка текста и выбранный стиль."""
    clean = _read_prompt("clean.txt")
    style_text = _read_prompt(STYLE_FILES[style])
    return clean + "\n\n" + style_text


def _build_prompt(text: str, reminder_file: str) -> str:
    """Надиктованный текст, а следом краткое напоминание о главных правилах.

    Инструкция длинная, и к концу модель часть правил забывает. Последние
    строки перед ответом она помнит лучше всего - туда и кладём главное.
    """
    return f"<text>\n{text}\n</text>\n\n" + _read_prompt(reminder_file)


def _call_ollama(system_prompt: str, text: str, model: str, reminder_file: str) -> str | None:
    payload = {
        "model": model,
        "system": system_prompt,
        "prompt": _build_prompt(text, reminder_file),
        "think": False,
        "stream": False,
        "keep_alive": KEEP_ALIVE,
        "options": {"temperature": TEMPERATURE},
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT_SEC)
        response.raise_for_status()
        return response.json().get("response", "")
    except requests.RequestException:
        logger.warning("Ollama не ответила, вставляю текст без редактуры", exc_info=True)
        return None


def _clean_response(raw: str) -> str:
    text = raw.strip()

    # модель иногда всё ещё думает, хотя мы просили think: false — на всякий случай убираем
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE).strip()

    # если модель скопировала наши теги <text>...</text> вместе с ответом
    match = re.search(r"<text>(.*?)</text>", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()

    for pattern in _PREFIX_PATTERNS:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

    if len(text) >= 2 and text[0] in "\"'«" and text[-1] in "\"'»":
        text = text[1:-1].strip()

    return text


def _looks_like_answer(original: str, edited: str) -> bool:
    """Похоже, что модель ответила на текст, а не отредактировала его."""
    if "```" in edited and "```" not in original:
        return True
    if len(edited) > len(original) * 2 + 20:
        return True
    return False


_WORD_RE = re.compile(r"\S+")
_EDGE_CHARS = ".,!?;:«»\"'()-—…"
# Союз в начале нового предложения разрешено убрать: "…лает, и решётка" → "…лает. Решётка"
_DROPPABLE_WORDS = {"и", "а", "но"}


def _words(text: str) -> list[str]:
    """Слова без знаков по краям. Точки внутри слова остаются: ivan.petrov@gmail.com."""
    result = []
    for token in _WORD_RE.findall(text.lower()):
        token = token.strip(_EDGE_CHARS)
        if token:
            result.append(token)
    return result


def only_punctuation_changed(before: str, after: str) -> bool:
    """Правда, если поменялись только знаки препинания, а слова остались те же.

    Второй запрос должен трогать лишь знаки. Если он подменил слово
    ("затем" → "тогда"), его результат отбрасывается.
    """
    old, new = _words(before), _words(after)
    i = j = 0
    while i < len(old) and j < len(new):
        if old[i] == new[j]:
            i += 1
            j += 1
        elif old[i] in _DROPPABLE_WORDS:
            i += 1
        else:
            return False
    while i < len(old) and old[i] in _DROPPABLE_WORDS:
        i += 1
    return i == len(old) and j == len(new)


def _ask(system_prompt: str, text: str, model: str, reminder_file: str) -> str | None:
    raw = _call_ollama(system_prompt, text, model, reminder_file)
    if raw is None:
        return None
    result = _clean_response(raw)
    return result or None


def _split_sentences(text: str, model: str) -> str:
    """Второй запрос: делит длинные предложения на простые. Слова не трогает.

    Две попытки: модель иногда подменяет слово, и тогда её ответ не годится.
    Если не вышло - возвращаем текст после чистки, он уже пригоден для вставки.
    """
    system_prompt = _read_prompt("punctuation.txt")
    for attempt in (1, 2):
        result = _ask(system_prompt, text, model, "punctuation_reminder.txt")
        if result is None:
            return text
        if only_punctuation_changed(text, result):
            return result
        logger.warning(
            "Запрос про пунктуацию подменил слова (попытка %d), его ответ отброшен: %s",
            attempt,
            result,
        )
    return text


def edit(text: str, style: str, model: str = DEFAULT_MODEL) -> str:
    """Словарь замен → чистка и стиль → пунктуация. При любой проблеме — как можно меньше правок."""
    if not text:
        return text

    text = apply_dictionary(text)

    if style == STYLE_RAW:
        return text

    cleaned = _ask(_build_system_prompt(style), text, model, "clean_reminder.txt")
    if cleaned is None:
        return text

    if _looks_like_answer(text, cleaned):
        logger.warning(
            "Похоже, модель ответила на текст вместо редактуры, вставляю без обработки. Ответ модели: %s",
            cleaned,
        )
        return text

    return _split_sentences(cleaned, model)


def warmup(model: str = DEFAULT_MODEL) -> None:
    """Прогревочный запрос, чтобы модель заранее загрузилась в видеопамять Ollama."""
    logger.info("Прогреваю модель редактуры (%s)...", model)
    # обе инструкции: Ollama запоминает каждую отдельно, прогревать надо тоже обе
    first = _call_ollama(_build_system_prompt("normal"), "это проверочный текст", model, "clean_reminder.txt")
    second = _call_ollama(_read_prompt("punctuation.txt"), "это проверочный текст", model, "punctuation_reminder.txt")
    if first is None or second is None:
        logger.warning("Не удалось прогреть Ollama — возможно, она не запущена")
    else:
        logger.info("Модель редактуры прогрета")
