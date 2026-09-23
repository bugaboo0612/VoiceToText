"""Редактор: словарь замен, затем чистка (уровень 1) и правка ошибок (уровень 2) через локальную модель в Ollama."""
import difflib
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

# Уровни обработки (в настройках хранятся под ключом "style")
STYLE_RAW = "raw"  # без обработки — Ollama не вызывается
STYLE_LEVEL1 = "level1"  # чистка: паразиты, оговорки, числа цифрами
STYLE_LEVEL2 = "level2"  # чистка, потом правка грамматики и знаков препинания

LEVEL1_PROMPT = "level1.txt"
LEVEL2_PROMPT = "level2.txt"

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


def _call_ollama(system_prompt: str, text: str, model: str) -> str | None:
    payload = {
        "model": model,
        "system": system_prompt,
        "prompt": f"<text>\n{text}\n</text>",
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


# Паразит в самом начале фразы модель иногда пропускает: он написан с заглавной
# буквы и похож на обычное начало предложения. Такие убираем сами, до Ollama.
# "Вот" сюда не входит: "Вот, что я думаю" - это не паразит.
_LEADING_FILLERS_RE = re.compile(
    r"(^|[.!?]\s+)((?:(?:ну|короче|типа|как бы|это самое|в общем|э-э|м-м)\s*,\s*)+)(\w)",
    re.IGNORECASE,
)


def _drop_leading_fillers(text: str) -> str:
    """"Ну, короче, надо…" → "Надо…". Только паразит с запятой в начале предложения."""
    return _LEADING_FILLERS_RE.sub(lambda m: m.group(1) + m.group(3).upper(), text)


def _looks_like_answer(original: str, edited: str) -> bool:
    """Похоже, что модель ответила на текст, а не отредактировала его."""
    if "```" in edited and "```" not in original:
        return True
    if len(edited) > len(original) * 2 + 20:
        return True
    return False


_WORD_RE = re.compile(r"\S+")
_EDGE_CHARS = ".,!?;:«»\"'()-—…"
# Служебные слова, которые редактор может добавить или убрать:
# "…лает, и решётка" → "…лает. Решётка", "обсудили о сроках" → "обсудили сроки".
# "не" и "ни" здесь нет: они меняют смысл на противоположный.
_SMALL_WORDS = {"и", "а", "но", "в", "во", "на", "о", "об", "с", "со", "к", "ко", "по", "из", "у", "за", "от", "до"}


def _words(text: str) -> list[str]:
    """Слова без знаков по краям. Точки внутри слова остаются: ivan.petrov@gmail.com."""
    result = []
    for token in _WORD_RE.findall(text.lower().replace("ё", "е")):
        token = token.strip(_EDGE_CHARS)
        if token:
            result.append(token)
    return result


def _same_word(old: str, new: str) -> bool:
    """То же слово с другим окончанием или исправленной буквой: "который" → "которые"."""
    if any(ch.isdigit() for ch in old + new):
        return old == new  # числа менять нельзя
    return old[0] == new[0] and difflib.SequenceMatcher(None, old, new).ratio() >= 0.6


def only_small_changes(before: str, after: str) -> bool:
    """Правда, если редактор исправил ошибки, а не переписал текст.

    Можно: менять знаки препинания и заглавные буквы, окончания и написание
    слов, добавлять и убирать служебные слова. Нельзя: менять числа,
    заменять слово другим ("затем" → "тогда"), добавлять или убирать
    слова по смыслу, менять больше чем примерно каждое пятое слово.
    """
    old, new = _words(before), _words(after)
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        changed += max(i2 - i1, j2 - j1)
        old_part = [w for w in old[i1:i2] if w not in _SMALL_WORDS]
        new_part = [w for w in new[j1:j2] if w not in _SMALL_WORDS]
        if len(old_part) != len(new_part):
            return False
        if not all(_same_word(a, b) for a, b in zip(old_part, new_part)):
            return False
    return changed <= max(2, len(old) // 5)


def _ask(system_prompt: str, text: str, model: str) -> str | None:
    raw = _call_ollama(system_prompt, text, model)
    if raw is None:
        return None
    result = _clean_response(raw)
    return result or None


def _proofread(text: str, model: str) -> str:
    """Уровень 2: исправляет грамматику и знаки препинания в тексте после чистки.

    Две попытки: модель иногда переписывает текст по-своему, и тогда её ответ не годится.
    Если не вышло - возвращаем текст после чистки, он уже пригоден для вставки.
    """
    system_prompt = _read_prompt(LEVEL2_PROMPT)
    for attempt in (1, 2):
        result = _ask(system_prompt, text, model)
        if result is None:
            return text
        if only_small_changes(text, result):
            return result
        logger.warning(
            "Редактор уровня 2 изменил слишком много (попытка %d), его ответ отброшен: %s",
            attempt,
            result,
        )
    return text


def edit(text: str, style: str, model: str = DEFAULT_MODEL) -> str:
    """Словарь замен → паразиты в начале фраз → уровень 1 (чистка) → уровень 2 (ошибки).

    При любой проблеме — как можно меньше правок.
    """
    if not text:
        return text

    text = apply_dictionary(text)

    if style == STYLE_RAW:
        return text

    text = _drop_leading_fillers(text)
    cleaned = _ask(_read_prompt(LEVEL1_PROMPT), text, model)
    if cleaned is None:
        return text

    if _looks_like_answer(text, cleaned):
        logger.warning(
            "Похоже, модель ответила на текст вместо редактуры, вставляю без обработки. Ответ модели: %s",
            cleaned,
        )
        return text

    if style == STYLE_LEVEL1:
        return cleaned
    return _proofread(cleaned, model)


def warmup(model: str = DEFAULT_MODEL) -> None:
    """Прогревочный запрос, чтобы модель заранее загрузилась в видеопамять Ollama."""
    logger.info("Прогреваю модель редактуры (%s)...", model)
    # обе инструкции: Ollama запоминает каждую отдельно, прогревать надо тоже обе
    first = _call_ollama(_read_prompt(LEVEL1_PROMPT), "это проверочный текст", model)
    second = _call_ollama(_read_prompt(LEVEL2_PROMPT), "это проверочный текст", model)
    if first is None or second is None:
        logger.warning("Не удалось прогреть Ollama — возможно, она не запущена")
    else:
        logger.info("Модель редактуры прогрета")
