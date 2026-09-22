"""Стенографист: звук -> текст, модель NVIDIA Parakeet."""
import logging

import numpy as np
import onnxruntime as ort

import onnx_asr

logger = logging.getLogger(__name__)

DEFAULT_MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"

# Модель за раз принимает не больше 20-30 секунд звука. Всё, что короче этого
# порога, распознаём целиком: тогда модель слышит фразу от начала до конца и
# сама решает, где пауза - конец предложения, а где просто раздумье.
MAX_AUDIO_NO_VAD_SEC = 20.0

# Пауза короче этого не считается концом предложения: запись не разрезается.
MIN_SILENCE_MS = 1500.0

# Модели распознавания, из которых можно выбирать в настройках.
AVAILABLE_MODELS = {
    "nemo-parakeet-tdt-0.6b-v3": "Parakeet (русский + английский, по умолчанию)",
    "gigaam-v3-e2e-rnnt": "GigaAM v3 (только русский, точнее на чистом русском)",
}


def _join_parts(parts: list[str]) -> str:
    """Склеивает куски длинной записи.

    Каждый кусок распознаётся отдельно, поэтому модель заканчивает его точкой.
    Если следующий кусок начинается с маленькой буквы - точка на стыке лишняя,
    это середина предложения.
    """
    result = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not result:
            result = part
            continue
        if result.endswith(".") and part[0].islower():
            result = result[:-1]
        result += " " + part
    return result


class Recognizer:
    """Держит модель распознавания загруженной в память."""

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        # Подгружает CUDA/cuDNN библиотеки, установленные как pip-пакеты,
        # иначе onnxruntime их не найдёт и молча перейдёт на процессор.
        ort.preload_dlls()
        ort.set_default_logger_severity(3)  # только ошибки, без технического шума

        self.model_name = model_name
        self.device = "GPU"
        try:
            model = onnx_asr.load_model(
                model_name, providers=["CUDAExecutionProvider"]
            )
            logger.info("Модель распознавания (%s) загружена на видеокарту", model_name)
        except Exception:
            logger.warning(
                "Не удалось загрузить модель на видеокарту, переходим на процессор",
                exc_info=True,
            )
            self.device = "CPU"
            model = onnx_asr.load_model(
                model_name, providers=["CPUExecutionProvider"]
            )

        self.model = model

        # VAD (детектор голоса) режет длинную запись на куски по паузам.
        # Нужен только для записей длиннее MAX_AUDIO_NO_VAD_SEC.
        vad = onnx_asr.load_vad("silero", providers=["CPUExecutionProvider"])
        self.model_with_vad = model.with_vad(
            vad,
            max_speech_duration_s=MAX_AUDIO_NO_VAD_SEC,
            min_silence_duration_ms=MIN_SILENCE_MS,
        )

    def recognize(self, waveform: np.ndarray, sample_rate: int = 16000) -> str:
        """Превращает звук (numpy-массив) в текст."""
        duration = len(waveform) / sample_rate

        if duration <= MAX_AUDIO_NO_VAD_SEC:
            return self.model.recognize(waveform, sample_rate=sample_rate).strip()

        logger.info("Запись длинная (%.1f с), режу её на куски по паузам", duration)
        parts = [
            segment.text
            for segment in self.model_with_vad.recognize(waveform, sample_rate=sample_rate)
        ]
        return _join_parts(parts)
