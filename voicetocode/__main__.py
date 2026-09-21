"""Точка входа: соединяет запись, распознавание, вставку текста, трей и настройки."""
import logging
import threading
import winsound

from voicetocode import settings
from voicetocode.hotkey import HotkeyListener
from voicetocode.paster import paste
from voicetocode.recognizer import Recognizer
from voicetocode.recorder import Recorder
from voicetocode.tray import Tray

logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 0.3  # короче — считаем случайным нажатием, игнорируем

recorder = Recorder()
recognizer: Recognizer | None = None
tray: Tray | None = None
exit_event = threading.Event()


def on_start() -> None:
    tray.set_state("recording")
    winsound.Beep(880, 120)
    recorder.start()


def on_stop() -> None:
    audio = recorder.stop()
    winsound.Beep(440, 120)
    tray.set_state("processing")
    try:
        duration = len(audio) / recorder.sample_rate
        if duration < MIN_DURATION_SEC:
            logger.info("Слишком короткая запись (%.2f с), игнорирую", duration)
            return

        text = recognizer.recognize(audio)
        if not text:
            logger.info("Распознавание не дало текста, игнорирую")
            return

        logger.info("Распознано: %s", text)
        paste(text)
    finally:
        tray.set_state("idle")


def on_mode_change(mode: str) -> None:
    hotkey_listener.mode = mode


def on_exit() -> None:
    hotkey_listener.stop()
    exit_event.set()


def setup_logging() -> None:
    settings.ensure_data_dir()
    log_file = settings.DATA_DIR / "voicetocode.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    global recognizer, tray, hotkey_listener

    setup_logging()

    current_settings = settings.load()

    print("Загружаю модель распознавания (в первый раз она скачается)...")
    recognizer = Recognizer()
    print(f"Модель загружена ({recognizer.device}). Готово — смотрите на значок в трее.")

    hotkey_listener = HotkeyListener(on_start, on_stop, mode=current_settings["hotkey_mode"])
    hotkey_listener.start()

    tray = Tray(current_settings, on_mode_change=on_mode_change, on_exit=on_exit)
    tray.run_detached()

    exit_event.wait()
    tray.stop()
    logger.info("Программа завершена")


if __name__ == "__main__":
    main()
