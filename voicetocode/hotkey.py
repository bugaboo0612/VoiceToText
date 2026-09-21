"""Пульт: глобальная горячая клавиша F9, оба режима."""
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

MODE_HOLD = "hold"  # держать и говорить
MODE_TOGGLE = "toggle"  # нажал - говорю - нажал


class HotkeyListener:
    """Нажали F9 -> on_start в фоновом потоке, отпустили -> on_stop в фоновом потоке.

    Режим "hold": запись идёт, пока клавиша зажата.
    Режим "toggle": первое нажатие - старт, следующее - стоп.

    Автоповтор Windows (несколько «нажатий» подряд, пока клавиша зажата)
    игнорируется. Сама клавиша F9 не доходит до других программ.

    Логика обрабатывается прямо в фильтре подавления событий (win32_event_filter),
    а не в обычных on_press/on_release: pynput не вызывает on_press/on_release
    для клавиши, которую мы подавили через suppress_event().
    """

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        mode: str = MODE_HOLD,
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self.mode = mode
        self._pressed = False  # клавиша физически зажата (нужно для игнора автоповтора)
        self._recording = False  # идёт запись (используется в режиме toggle)
        self._listener = keyboard.Listener(win32_event_filter=self._win32_event_filter)

    def _win32_event_filter(self, msg, data) -> None:
        if data.vkCode != VK_F9:
            return

        if msg in _PRESS_MESSAGES:
            if not self._pressed:
                self._pressed = True
                self._handle_press()
        elif msg in _RELEASE_MESSAGES:
            self._pressed = False
            if self.mode == MODE_HOLD:
                self._handle_release()

        self._listener.suppress_event()

    def _handle_press(self) -> None:
        if self.mode == MODE_HOLD:
            self._recording = True
            threading.Thread(target=self._on_start, daemon=True).start()
        else:  # MODE_TOGGLE
            if self._recording:
                self._recording = False
                threading.Thread(target=self._on_stop, daemon=True).start()
            else:
                self._recording = True
                threading.Thread(target=self._on_start, daemon=True).start()

    def _handle_release(self) -> None:
        if self._recording:
            self._recording = False
            threading.Thread(target=self._on_stop, daemon=True).start()

    def start(self) -> None:
        self._listener.start()
        logger.info("Слушаю горячую клавишу F9 (режим: %s)", self.mode)

    def stop(self) -> None:
        self._listener.stop()

    def join(self) -> None:
        self._listener.join()
