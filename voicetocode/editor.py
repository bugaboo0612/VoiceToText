"""Редактор: чистка текста и смена стиля через локальную модель в Ollama."""
import logging
import re
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen3:8b"
TIMEOUT_SEC = 20
KEEP_ALIVE = "30m"
TEMPERATURE = 0.2

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"

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


def _read_prompt(filename: str) -> str:
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _build_system_prompt(style: str) -> str:
    base = _read_prompt("base.txt")
    style_text = _read_prompt(STYLE_FILES[style])
    return base + "\n\n" + style_text


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


def _looks_like_answer(original: str, edited: str) -> bool:
    """Похоже, что модель ответила на текст, а не отредактировала его."""
    if "```" in edited and "```" not in original:
        return True
    if len(edited) > len(original) * 2 + 20:
        return True
    return False


def edit(text: str, style: str, model: str = DEFAULT_MODEL) -> str:
    """Чистит текст и, если нужно, меняет стиль. При любой проблеме отдаёт исходный текст."""
    if style == STYLE_RAW or not text:
        return text

    raw = _call_ollama(_build_system_prompt(style), text, model)
    if raw is None:
        return text

    cleaned = _clean_response(raw)

    if not cleaned:
        return text

    if _looks_like_answer(text, cleaned):
        logger.warning(
            "Похоже, модель ответила на текст вместо редактуры, вставляю без обработки. Ответ модели: %s",
            cleaned,
        )
        return text

    return cleaned


def warmup(model: str = DEFAULT_MODEL) -> None:
    """Прогревочный запрос, чтобы модель заранее загрузилась в видеопамять Ollama."""
    logger.info("Прогреваю модель редактуры (%s)...", model)
    result = _call_ollama(_build_system_prompt("normal"), "это проверочный текст", model)
    if result is None:
        logger.warning("Не удалось прогреть Ollama — возможно, она не запущена")
    else:
        logger.info("Модель редактуры прогрета")
