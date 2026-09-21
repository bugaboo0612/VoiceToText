"""Уши: запись звука с микрофона."""
import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000  # Гц, моно — то, что ждёт модель распознавания


def record_seconds(duration: float, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Записывает звук с микрофона по умолчанию заданное число секунд."""
    logger.info("Начата запись на %.1f сек", duration)
    audio = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    return audio.reshape(-1)
