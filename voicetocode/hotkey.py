"""Пульт: глобальная горячая клавиша F9, режим «держать и говорить»."""
import logging
import threading
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

VK_F9 = 0x78  # код клавиши F9 в Windows

# Коды сообщений Windows о нажатии/отпускании клавиши
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_KEYUP = 0x0101
_WM_SYSKEYUP = 0x0105
_PRESS_MESSAGES = (_WM_KEYDOWN, _WM_SYSKEYDOWN)
_RELEASE_MESSAGES = (_WM_KEYUP, _WM_SYSKEYUP)


class HotkeyListener:
    """Нажали F9 -> on_start в фоновом потоке, отпустили -> on_stop в фоновом потоке.

    Автоповтор Windows (несколько «нажатий» подряд, пока клавиша зажата)
    игнорируется: on_start вызывается один раз, пока клавиша не отпущена.
    Сама клавиша F9 не доходит до других программ.

    Логика обрабатывается прямо в фильтре подавления событий (win32_event_filter),
    а не в обычных on_press/on_release: pynput не вызывает on_press/on_release
    для клавиши, которую мы подавили через suppress_event().
    """

    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None]) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._pressed = False
        self._listener = keyboard.Listener(win32_event_filter=self._win32_event_filter)

    def _win32_event_filter(self, msg, data) -> None:
        if data.vkCode != VK_F9:
            return

        if msg in _PRESS_MESSAGES:
            if not self._pressed:
                self._pressed = True
                threading.Thread(target=self._on_start, daemon=True).start()
        elif msg in _RELEASE_MESSAGES:
            if self._pressed:
                self._pressed = False
                threading.Thread(target=self._on_stop, daemon=True).start()

        self._listener.suppress_event()

    def start(self) -> None:
        self._listener.start()
        logger.info("Слушаю горячую клавишу F9")

    def stop(self) -> None:
        self._listener.stop()

    def join(self) -> None:
        self._listener.join()
