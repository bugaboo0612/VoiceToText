"""Руки: кладут текст в буфер обмена и вставляют его в активное окно."""
import logging
import time

import pyperclip
from pynput.keyboard import Controller, Key

logger = logging.getLogger(__name__)

_keyboard = Controller()


def paste(text: str) -> None:
    """Кладёт текст в буфер обмена и нажимает Ctrl+V. Текст остаётся в буфере."""
    pyperclip.copy(text)
    time.sleep(0.05)  # дать системе обновить буфер обмена перед вставкой
    with _keyboard.pressed(Key.ctrl):
        _keyboard.press("v")
        _keyboard.release("v")
    logger.info("Текст вставлен (%d символов)", len(text))
