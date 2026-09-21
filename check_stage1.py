"""Ручная проверка Этапа 1: записать 5 секунд и показать распознанный текст.

Запуск:
    .venv\\Scripts\\python check_stage1.py
"""
import logging

from voicetocode.recognizer import Recognizer
from voicetocode.recorder import record_seconds

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def main() -> None:
    print("Загружаю модель распознавания (в первый раз она скачается, это может занять пару минут)...")
    recognizer = Recognizer()
    print(f"Модель загружена. Используется: {recognizer.device}.")

    input("Нажмите Enter и сразу говорите — запись пойдёт 5 секунд...")
    print("Идёт запись...")
    audio = record_seconds(5.0)
    print("Запись окончена, распознаю...")

    text = recognizer.recognize(audio)
    print("\nРаспознанный текст:")
    print(text)


if __name__ == "__main__":
    main()
