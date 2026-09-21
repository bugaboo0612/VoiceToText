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
