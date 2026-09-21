"""Уши: запись звука с микрофона."""
import logging
import threading

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


class Recorder:
    """Запись неизвестной заранее длины: start() -> ... -> stop() отдаёт звук."""

    def __init__(self, sample_rate: int = SAMPLE_RATE) -> None:
        self.sample_rate = sample_rate
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._started_event = threading.Event()

    def start(self) -> None:
        self._frames = []
        self._started_event.clear()

        def callback(indata, frames, time_info, status) -> None:
            if status:
                logger.warning("Проблема при записи звука: %s", status)
            with self._lock:
                self._frames.append(indata.copy())

        self._stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, dtype="float32", callback=callback
        )
        self._stream.start()
        self._started_event.set()
        logger.info("Запись началась")

    def stop(self) -> np.ndarray:
        # ждём, если stop() вызвали раньше, чем start() успел запустить поток
        self._started_event.wait(timeout=2.0)
        if self._stream is None:
            return np.zeros(0, dtype="float32")
        self._stream.stop()
        self._stream.close()
        self._stream = None
        with self._lock:
            frames, self._frames = self._frames, []
        logger.info("Запись остановлена")
        if not frames:
            return np.zeros(0, dtype="float32")
        return np.concatenate(frames, axis=0).reshape(-1)
