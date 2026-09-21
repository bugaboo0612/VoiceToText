"""История последних 100 диктовок (сырой и итоговый текст)."""
import logging
from datetime import datetime

from voicetocode import settings

logger = logging.getLogger(__name__)

HISTORY_FILE = settings.DATA_DIR / "history.txt"
MAX_ENTRIES = 100
_MARK = "=== "


def ensure_file() -> None:
    settings.ensure_data_dir()
    if not HISTORY_FILE.exists():
        try:
            HISTORY_FILE.write_text("", encoding="utf-8")
        except OSError:
            logger.warning("Не удалось создать файл истории", exc_info=True)


def _read_entries() -> list[str]:
    if not HISTORY_FILE.exists():
        return []
    try:
        content = HISTORY_FILE.read_text(encoding="utf-8")
    except OSError:
        logger.warning("Не удалось прочитать историю", exc_info=True)
        return []
    blocks = [b.strip() for b in content.split(_MARK) if b.strip()]
    return [_MARK + b for b in blocks]


def add_entry(raw_text: str, final_text: str) -> None:
    """Добавляет запись в историю, оставляя не больше MAX_ENTRIES последних."""
    settings.ensure_data_dir()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{_MARK}{timestamp} ===\nСырой текст: {raw_text}\nИтоговый текст: {final_text}"

    entries = _read_entries()
    entries.append(entry)
    entries = entries[-MAX_ENTRIES:]

    try:
        HISTORY_FILE.write_text("\n\n".join(entries) + "\n", encoding="utf-8")
    except OSError:
        logger.warning("Не удалось записать историю", exc_info=True)
