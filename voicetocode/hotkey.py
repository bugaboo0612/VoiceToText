"""Пульт: глобальная горячая клавиша (сочетание клавиш), оба режима."""
import logging
import threading
from typing import Callable

from pynput import keyboard

logger = logging.getLogger(__name__)

# Коды сообщений Windows о нажатии/отпускании клавиши
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_KEYUP = 0x0101
_WM_SYSKEYUP = 0x0105
_PRESS_MESSAGES = (_WM_KEYDOWN, _WM_SYSKEYDOWN)
_RELEASE_MESSAGES = (_WM_KEYUP, _WM_SYSKEYUP)

MODE_HOLD = "hold"  # держать и говорить
MODE_TOGGLE = "toggle"  # нажал - говорю - нажал

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
MODIFIER_VKS = {VK_SHIFT, VK_CONTROL, VK_MENU}

# Windows на уровне низкоуровневого хука часто присылает отдельные коды для
# левой/правой клавиши (например Ctrl слева = 0xA2), а не общий 0x11 —
# приводим их все к одному общему коду.
_MODIFIER_NORMALIZE = {
    VK_SHIFT: VK_SHIFT,
    0xA0: VK_SHIFT,  # VK_LSHIFT
    0xA1: VK_SHIFT,  # VK_RSHIFT
    VK_CONTROL: VK_CONTROL,
    0xA2: VK_CONTROL,  # VK_LCONTROL
    0xA3: VK_CONTROL,  # VK_RCONTROL
    VK_MENU: VK_MENU,
    0xA4: VK_MENU,  # VK_LMENU
    0xA5: VK_MENU,  # VK_RMENU
}


def _normalize_modifier(vk: int) -> int | None:
    """Общий код, если vk — это (левый/правый) Ctrl/Alt/Shift, иначе None."""
    return _MODIFIER_NORMALIZE.get(vk)

# Человекочитаемые названия клавиш для окна настроек
VK_NAMES = {
    VK_SHIFT: "Shift",
    VK_CONTROL: "Ctrl",
    VK_MENU: "Alt",
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x1B: "Esc",
    0x20: "Пробел",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Стрелка влево",
    0x26: "Стрелка вверх",
    0x27: "Стрелка вправо",
    0x28: "Стрелка вниз",
    0x2D: "Insert",
    0x2E: "Delete",
    0x14: "CapsLock",
    0x90: "NumLock",
    0x91: "ScrollLock",
}
for _i in range(12):
    VK_NAMES[0x70 + _i] = f"F{_i + 1}"
for _i in range(10):
    VK_NAMES[0x30 + _i] = str(_i)  # цифры на основной клавиатуре
    VK_NAMES[0x60 + _i] = f"Num{_i}"  # цифры на цифровой клавиатуре
for _i in range(26):
    VK_NAMES[0x41 + _i] = chr(ord("A") + _i)


def vk_name(vk: int) -> str:
    return VK_NAMES.get(vk, f"клавиша 0x{vk:02X}")


def combo_name(modifiers: set, main_vk: int | None) -> str:
    parts = [vk_name(m) for m in sorted(modifiers)]
    if main_vk is not None:
        parts.append(vk_name(main_vk))
    return " + ".join(parts) if parts else "не задано"


def combo_from_settings(hotkey_vks: list) -> tuple[set, int | None]:
    """Разбирает список кодов клавиш из настроек на модификаторы и основную клавишу."""
    modifiers = {v for v in hotkey_vks if v in MODIFIER_VKS}
    main_candidates = [v for v in hotkey_vks if v not in MODIFIER_VKS]
    main_vk = main_candidates[0] if main_candidates else None
    return modifiers, main_vk


def _vk_of(key) -> int | None:
    vk = getattr(key, "vk", None)
    if vk is not None:
        return vk
    value = getattr(key, "value", None)
    return getattr(value, "vk", None) if value is not None else None


class HotkeyListener:
    """Сочетание клавиш: модификаторы (Ctrl/Alt/Shift) + одна основная клавиша.

    Режим "hold": запись идёт, пока основная клавиша зажата (модификаторы должны
    быть уже нажаты в момент нажатия основной клавиши).
    Режим "toggle": первое полное нажатие - старт, следующее - стоп.

    Модификаторы никогда не подавляются (чтобы не ломать чужие сочетания вроде
    Ctrl+C), подавляется только основная клавиша, и только когда модификаторы
    уже были нажаты - так сочетание не мешает остальной системе.
    """

    def __init__(
        self,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        mode: str = MODE_HOLD,
        modifiers: set | None = None,
        main_vk: int | None = 0x78,  # F9 по умолчанию
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self.mode = mode
        self.modifiers = set(modifiers) if modifiers else set()
        self.main_vk = main_vk
        self._modifiers_down: set = set()
        self._main_pressed = False  # основная клавиша физически зажата
        self._recording = False
        self._listener = keyboard.Listener(win32_event_filter=self._win32_event_filter)

    def _win32_event_filter(self, msg, data) -> None:
        vk = data.vkCode
        normalized = _normalize_modifier(vk)

        if normalized is not None:
            if msg in _PRESS_MESSAGES:
                self._modifiers_down.add(normalized)
            elif msg in _RELEASE_MESSAGES:
                self._modifiers_down.discard(normalized)
            return  # модификаторы никогда не подавляем

        if self.main_vk is None or vk != self.main_vk:
            return

        if msg in _PRESS_MESSAGES:
            if not self._main_pressed and self.modifiers <= self._modifiers_down:
                self._main_pressed = True
                self._handle_press()
                self._listener.suppress_event()
            elif self._main_pressed:
                self._listener.suppress_event()  # автоповтор
        elif msg in _RELEASE_MESSAGES:
            if self._main_pressed:
                self._main_pressed = False
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

    def set_hotkey(self, modifiers: set, main_vk: int | None) -> None:
        self.modifiers = set(modifiers)
        self.main_vk = main_vk
        self._modifiers_down.clear()
        self._main_pressed = False

    def start(self) -> None:
        self._listener.start()
        logger.info(
            "Слушаю горячую клавишу %s (режим: %s)",
            combo_name(self.modifiers, self.main_vk),
            self.mode,
        )

    def stop(self) -> None:
        self._listener.stop()

    def join(self) -> None:
        self._listener.join()


def capture_combo(on_captured: Callable[[set, int | None], None]) -> "keyboard.Listener":
    """Слушает следующее нажатое и полностью отпущенное сочетание клавиш.

    Ничего не подавляет (пользователь должен видеть свои нажатия как обычно).
    Вызывает on_captured(modifiers, main_vk) один раз, когда все клавиши отпущены.
    """
    pressed: set = set()
    seen: set = set()

    def on_event(msg, data) -> None:
        vk = data.vkCode
        normalized = _normalize_modifier(vk)
        tracked = normalized if normalized is not None else vk
        if msg in _PRESS_MESSAGES:
            pressed.add(tracked)
            seen.add(tracked)
        elif msg in _RELEASE_MESSAGES:
            pressed.discard(tracked)
            if not pressed and seen:
                modifiers = {v for v in seen if v in MODIFIER_VKS}
                main_candidates = [v for v in seen if v not in MODIFIER_VKS]
                main_vk = main_candidates[-1] if main_candidates else None
                listener.stop()
                on_captured(modifiers, main_vk)

    listener = keyboard.Listener(win32_event_filter=on_event)
    listener.start()
    return listener
