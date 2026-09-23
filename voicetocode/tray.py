"""Пульт: значок в трее и его меню."""
import logging
import os
import subprocess

import pystray
from PIL import Image, ImageDraw

from voicetocode import editor, history, settings

logger = logging.getLogger(__name__)

COLOR_IDLE = "grey"
COLOR_RECORDING = "red"
COLOR_PROCESSING = "#e6c200"  # жёлтый

STYLE_LABELS = {
    "raw": "Без обработки",
    "level1": "Уровень 1 — Чистка",
    "level2": "Уровень 2 — Редактор",
}
MODE_LABELS = {
    "hold": "Удержание",
    "toggle": "Переключение",
}


def _make_image(color: str) -> Image.Image:
    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = 6
    draw.ellipse((margin, margin, size - margin, size - margin), fill=color)
    return image


_ICONS = {
    "idle": _make_image(COLOR_IDLE),
    "recording": _make_image(COLOR_RECORDING),
    "processing": _make_image(COLOR_PROCESSING),
}


class Tray:
    """Значок в трее: меняет цвет и хранит меню выбора стиля/режима клавиши."""

    def __init__(
        self,
        current_settings: dict,
        on_mode_change,
        on_exit,
        on_open_settings,
        on_settings_changed,
        on_check_updates,
    ) -> None:
        self._settings = current_settings
        self._on_mode_change = on_mode_change
        self._on_exit = on_exit
        self._on_open_settings = on_open_settings
        self._on_settings_changed = on_settings_changed
        self._on_check_updates = on_check_updates
        self.icon = pystray.Icon(
            "VoiceToText",
            _ICONS["idle"],
            "VoiceToText — ждёт",
            menu=self._build_menu(),
        )

    def _build_menu(self) -> pystray.Menu:
        style_items = [
            pystray.MenuItem(
                label,
                self._make_style_setter(key),
                checked=self._make_style_checker(key),
                radio=True,
            )
            for key, label in STYLE_LABELS.items()
        ]
        mode_items = [
            pystray.MenuItem(
                label,
                self._make_mode_setter(key),
                checked=self._make_mode_checker(key),
                radio=True,
            )
            for key, label in MODE_LABELS.items()
        ]
        return pystray.Menu(
            pystray.MenuItem("Обработка", pystray.Menu(*style_items)),
            pystray.MenuItem("Режим клавиши", pystray.Menu(*mode_items)),
            pystray.MenuItem("Настройки…", self._open_settings),
            pystray.MenuItem("Проверить обновление моделей…", self._check_updates),
            pystray.MenuItem("Открыть словарь", self._open_dictionary),
            pystray.MenuItem("Открыть историю", self._open_history),
            pystray.MenuItem("Открыть папку данных", self._open_data_folder),
            pystray.MenuItem("Выход", self._exit),
        )

    def _make_style_setter(self, key: str):
        def setter(icon, item) -> None:
            self._settings["style"] = key
            settings.save(self._settings)
            self._on_settings_changed()
            logger.info("Обработка изменена на: %s", key)

        return setter

    def _make_style_checker(self, key: str):
        return lambda item: self._settings["style"] == key

    def _make_mode_setter(self, key: str):
        def setter(icon, item) -> None:
            self._settings["hotkey_mode"] = key
            settings.save(self._settings)
            self._on_mode_change(key)
            self._on_settings_changed()
            logger.info("Режим клавиши изменён на: %s", key)

        return setter

    def _make_mode_checker(self, key: str):
        return lambda item: self._settings["hotkey_mode"] == key

    def _open_settings(self, icon, item) -> None:
        self._on_open_settings()

    def _check_updates(self, icon, item) -> None:
        self._on_check_updates()

    def _open_dictionary(self, icon, item) -> None:
        editor.ensure_dictionary_file()
        subprocess.Popen(["notepad.exe", str(editor.DICTIONARY_FILE)])

    def _open_history(self, icon, item) -> None:
        history.ensure_file()
        subprocess.Popen(["notepad.exe", str(history.HISTORY_FILE)])

    def _open_data_folder(self, icon, item) -> None:
        settings.ensure_data_dir()
        os.startfile(settings.DATA_DIR)

    def _exit(self, icon, item) -> None:
        icon.stop()
        self._on_exit()

    def set_state(self, state: str) -> None:
        """state: 'idle' | 'recording' | 'processing'."""
        self.icon.icon = _ICONS[state]

    def refresh_menu(self) -> None:
        """Перечитать отметки в меню (обработка/режим), если их изменили извне (окно настроек)."""
        self.icon.update_menu()

    def run_detached(self) -> None:
        self.icon.run_detached()

    def stop(self) -> None:
        self.icon.stop()
