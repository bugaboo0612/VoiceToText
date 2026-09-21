"""Точка входа: соединяет запись, распознавание и вставку текста."""
import logging
import winsound

from voicetocode.hotkey import HotkeyListener
from voicetocode.paster import paste
from voicetocode.recognizer import Recognizer
from voicetocode.recorder import Recorder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

MIN_DURATION_SEC = 0.3  # короче — считаем случайным нажатием, игнорируем

recorder = Recorder()
recognizer: Recognizer | None = None


def on_start() -> None:
    winsound.Beep(880, 120)
    recorder.start()


def on_stop() -> None:
    audio = recorder.stop()
    winsound.Beep(440, 120)

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


def main() -> None:
    global recognizer
    print("Загружаю модель распознавания (в первый раз она скачается)...")
    recognizer = Recognizer()
    print(f"Модель загружена ({recognizer.device}). Зажмите F9 и говорите.")

    listener = HotkeyListener(on_start, on_stop)
    listener.start()
    listener.join()


if __name__ == "__main__":
    main()
