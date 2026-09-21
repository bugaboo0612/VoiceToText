"""Автозапуск вместе с Windows: запись в реестр (без PowerShell — некоторые
антивирусы блокируют создание ярлыков в папке автозагрузки как подозрительное)."""
import logging
import winreg
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
RUN_BAT = PROJECT_DIR / "run.bat"

_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "VoiceToCode"


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
            return True
    except OSError:
        return False


def enable(run_bat: Path = RUN_BAT) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, f'"{run_bat}"')
        return True
    except OSError:
        logger.warning("Не удалось включить автозапуск", exc_info=True)
        return False


def disable() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
        return True
    except FileNotFoundError:
        return True  # уже выключено
    except OSError:
        logger.warning("Не удалось выключить автозапуск", exc_info=True)
        return False
