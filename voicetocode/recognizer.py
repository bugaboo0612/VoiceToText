"""Стенографист: звук -> текст, модель NVIDIA Parakeet."""
import logging

import numpy as np
import onnxruntime as ort

import onnx_asr

logger = logging.getLogger(__name__)

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"


class Recognizer:
    """Держит модель распознавания загруженной в память."""

    def __init__(self) -> None:
        # Подгружает CUDA/cuDNN библиотеки, установленные как pip-пакеты,
        # иначе onnxruntime их не найдёт и молча перейдёт на процессор.
        ort.preload_dlls()
        ort.set_default_logger_severity(3)  # только ошибки, без технического шума

        self.device = "GPU"
        try:
            self.model = onnx_asr.load_model(
                MODEL_NAME, providers=["CUDAExecutionProvider"]
            )
            logger.info("Модель распознавания загружена на видеокарту")
        except Exception:
            logger.warning(
                "Не удалось загрузить модель на видеокарту, переходим на процессор",
                exc_info=True,
            )
            self.device = "CPU"
            self.model = onnx_asr.load_model(
                MODEL_NAME, providers=["CPUExecutionProvider"]
            )

    def recognize(self, waveform: np.ndarray, sample_rate: int = 16000) -> str:
        """Превращает звук (numpy-массив) в текст."""
        text = self.model.recognize(waveform, sample_rate=sample_rate)
        return text.strip()
