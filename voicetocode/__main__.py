"""Точка входа: соединяет запись, распознавание, вставку текста, трей и настройки."""
import ctypes
import logging
import sys
import tkinter as tk
import winsound

from voicetocode import editor, history, hotkey, settings
from voicetocode.hotkey import HotkeyListener
from voicetocode.paster import paste
from voicetocode.recognizer import Recognizer
from voicetocode.recorder import Recorder
from voicetocode.settings_window import SettingsWindow
from voicetocode.tray import Tray

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 0.3  # короче — считаем случайным нажатием, игнорируем
_MUTEX_NAME = "VoiceToCode_SingleInstance"
_ERROR_ALREADY_EXISTS = 183
_mutex_handle = None  # держим ссылку, иначе мьютекс освободится сборщиком мусора


def _ensure_single_instance() -> bool:
    """True, если это первая копия программы. Если уже запущена другая — False."""
    global _mutex_handle
    _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    already_running = ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS
    return not already_running

recorder = Recorder()
recognizer: Recognizer | None = None
tray: Tray | None = None
app_settings: dict | None = None
root: tk.Tk | None = None
hotkey_listener: HotkeyListener | None = None
settings_window: SettingsWindow | None = None


def _beep(frequency: int, duration_ms: int) -> None:
    if app_settings.get("sound_enabled", True):
        winsound.Beep(frequency, duration_ms)


def on_start() -> None:
    tray.set_state("recording")
    _beep(880, 120)
    recorder.start()


def on_stop() -> None:
    audio = recorder.stop()
    _beep(440, 120)
    tray.set_state("processing")
    try:
        duration = len(audio) / recorder.sample_rate
        if duration < MIN_DURATION_SEC:
            logger.info("Слишком короткая запись (%.2f с), игнорирую", duration)
            return

        raw_text = recognizer.recognize(audio)
        if not raw_text:
            logger.info("Распознавание не дало текста, игнорирую")
            return
        logger.info("Распознано: %s", raw_text)

        final_text = editor.edit(raw_text, app_settings["style"], model=app_settings["ollama_model"])
        logger.info("После редактуры: %s", final_text)

        paste(final_text)
        history.add_entry(raw_text, final_text)
    finally:
        tray.set_state("idle")


def on_mode_change(mode: str) -> None:
    hotkey_listener.mode = mode


def on_settings_saved() -> None:
    logger.info("Настройки сохранены: %s", app_settings)
    tray.refresh_menu()


def on_tray_settings_changed() -> None:
    root.after(0, settings_window.refresh)


def on_exit() -> None:
    hotkey_listener.stop()
    tray.stop()
    root.after(0, root.quit)


def setup_logging() -> None:
    settings.ensure_data_dir()
    log_file = settings.DATA_DIR / "voicetocode.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    global recognizer, tray, hotkey_listener, app_settings, root, settings_window

    if not _ensure_single_instance():
        ctypes.windll.user32.MessageBoxW(
            None, "VoiceToCode уже запущена — смотрите значок в трее.", "VoiceToCode", 0x40
        )
        sys.exit(0)

    setup_logging()

    app_settings = settings.load()
    recorder.device_name = app_settings["microphone"]
    editor.ensure_dictionary_file()
    history.ensure_file()

    print("Загружаю модель распознавания (в первый раз она скачается)...")
    recognizer = Recognizer()
    print(f"Модель загружена ({recognizer.device}).")

    print("Прогреваю модель редактуры в Ollama...")
    editor.warmup(app_settings["ollama_model"])
    print("Готово — смотрите на значок в трее.")

    modifiers, main_vk = hotkey.combo_from_settings(app_settings["hotkey_vks"])
    hotkey_listener = HotkeyListener(
        on_start, on_stop, mode=app_settings["hotkey_mode"], modifiers=modifiers, main_vk=main_vk
    )
    hotkey_listener.start()

    # tkinter обязан жить в главном потоке; окно настроек скрыто, пока не понадобится
    root = tk.Tk()
    root.withdraw()

    settings_window = SettingsWindow(root, app_settings, hotkey_listener, recorder, on_settings_saved)

    tray = Tray(
        app_settings,
        on_mode_change=on_mode_change,
        on_exit=on_exit,
        on_open_settings=lambda: root.after(0, settings_window.open),
        on_settings_changed=on_tray_settings_changed,
    )
    tray.run_detached()

    root.mainloop()
    logger.info("Программа завершена")


if __name__ == "__main__":
    main()
