"""Руки: кладут текст в буфер обмена и вставляют его в активное окно."""
import logging
import time

import pyperclip
from pynput.keyboard import Controller, Key, KeyCode

logger = logging.getLogger(__name__)

_keyboard = Controller()

# Код клавиши V по коду виртуальной клавиши Windows, а не по символу:
# если передать pynput букву "v" как обычный текст, она может напечататься
# напрямую (как юникод-символ), и Windows не увидит зажатый Ctrl.
_VK_V = KeyCode.from_vk(0x56)


def paste(text: str) -> None:
    """Кладёт текст в буфер обмена и нажимает Ctrl+V. Текст остаётся в буфере."""
    pyperclip.copy(text)
    time.sleep(0.05)  # дать системе обновить буфер обмена перед вставкой

    _keyboard.press(Key.ctrl)
    time.sleep(0.02)
    _keyboard.press(_VK_V)
    time.sleep(0.02)
    _keyboard.release(_VK_V)
    time.sleep(0.02)
    _keyboard.release(Key.ctrl)

    logger.info("Текст вставлен (%d символов)", len(text))
