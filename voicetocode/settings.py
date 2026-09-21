"""Настройки: чтение и запись, значения по умолчанию."""
import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ["APPDATA"]) / "VoiceToCode"
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULTS = {
    "hotkey_mode": "hold",  # "hold" (удержание) или "toggle" (переключение)
    "style": "normal",  # "raw", "normal", "polite", "professional"
    "hotkey_vks": [0x78],  # коды клавиш сочетания, по умолчанию одна F9
    "microphone": None,  # название микрофона (по нему заново ищется устройство) или None
    "ollama_model": "qwen3:8b",
    "sound_enabled": True,
}

VALID_HOTKEY_MODES = ("hold", "toggle")
VALID_STYLES = ("raw", "normal", "polite", "professional")

_lock = threading.Lock()


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load() -> dict:
    """Читает настройки из файла, недостающие или неверные поля дополняет по умолчанию."""
    ensure_data_dir()
    settings = dict(DEFAULTS)
    with _lock:
        if SETTINGS_FILE.exists():
            try:
                saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                settings.update(saved)
            except (json.JSONDecodeError, OSError):
                logger.warning("Не удалось прочитать файл настроек, использую значения по умолчанию", exc_info=True)

    if settings.get("hotkey_mode") not in VALID_HOTKEY_MODES:
        settings["hotkey_mode"] = DEFAULTS["hotkey_mode"]
    if settings.get("style") not in VALID_STYLES:
        settings["style"] = DEFAULTS["style"]
    hotkey_vks = settings.get("hotkey_vks")
    if not isinstance(hotkey_vks, list) or not all(isinstance(v, int) for v in hotkey_vks) or not hotkey_vks:
        settings["hotkey_vks"] = list(DEFAULTS["hotkey_vks"])
    if not isinstance(settings.get("microphone"), (str, type(None))):
        settings["microphone"] = DEFAULTS["microphone"]
    if not isinstance(settings.get("ollama_model"), str) or not settings["ollama_model"]:
        settings["ollama_model"] = DEFAULTS["ollama_model"]
    if not isinstance(settings.get("sound_enabled"), bool):
        settings["sound_enabled"] = DEFAULTS["sound_enabled"]

    return settings


def save(settings: dict) -> None:
    ensure_data_dir()
    with _lock:
        try:
            SETTINGS_FILE.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            logger.warning("Не удалось сохранить настройки", exc_info=True)
