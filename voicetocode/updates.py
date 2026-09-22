"""Проверка обновлений языковых моделей: модель редактуры (Ollama) и модель распознавания речи.

Единственное место, где программа выходит в интернет после установки, и только
по просьбе владельца. Наружу уходит лишь название модели: ни голос, ни текст
диктовок здесь не участвуют.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from voicetocode.recognizer import AVAILABLE_MODELS

logger = logging.getLogger(__name__)

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"  # не "localhost": на Windows его резолвинг иногда занимает 2+ секунды
OLLAMA_PULL_URL = "http://127.0.0.1:11434/api/pull"
OLLAMA_MANIFEST_URL = "https://registry.ollama.ai/v2/{repo}/manifests/{tag}"
OLLAMA_MANIFEST_ACCEPT = "application/vnd.docker.distribution.manifest.v2+json"
HF_MODEL_URL = "https://huggingface.co/api/models/{repo}"

CHECK_TIMEOUT_SEC = 15
CONNECT_TIMEOUT_SEC = 15
DOWNLOAD_TIMEOUT_SEC = 600  # ждём столько между кусками скачивания, а не всё скачивание целиком

# Где на Hugging Face лежат модели распознавания (те же адреса использует onnx-asr).
RECOGNITION_REPOS = {
    "nemo-parakeet-tdt-0.6b-v3": "istupakov/parakeet-tdt-0.6b-v3-onnx",
    "gigaam-v3-e2e-rnnt": "istupakov/gigaam-v3-onnx",
}

KIND_OLLAMA = "ollama"
KIND_RECOGNITION = "recognition"

UP_TO_DATE = "up_to_date"  # последняя версия
UPDATE_AVAILABLE = "update_available"  # вышла новая
UNKNOWN = "unknown"  # проверить не удалось


@dataclass
class ModelStatus:
    """Результат проверки одной модели."""

    kind: str  # KIND_OLLAMA или KIND_RECOGNITION
    name: str  # название модели, как её знает программа
    title: str  # как показать владельцу
    state: str  # UP_TO_DATE / UPDATE_AVAILABLE / UNKNOWN
    detail: str  # понятное пояснение

    @property
    def line(self) -> str:
        return f"{self.title}: {self.detail}"


# --- модель редактуры (Ollama) -------------------------------------------------


def _with_tag(model: str) -> str:
    """Ollama хранит модель без тега как ":latest"."""
    return model if ":" in model else f"{model}:latest"


def split_ollama_name(model: str) -> tuple[str, str] | None:
    """"qwen3:8b" -> ("library/qwen3", "8b"). None, если модель не с сайта ollama.com."""
    name, _, tag = model.partition(":")
    name, tag = name.strip("/"), tag or "latest"
    if not name:
        return None
    parts = name.split("/")
    if len(parts) == 1:
        return f"library/{parts[0]}", tag
    # точка в первой части - это адрес чужого хранилища (например hf.co/...), его не проверяем
    if len(parts) == 2 and "." not in parts[0]:
        return f"{parts[0]}/{parts[1]}", tag
    return None


def _local_ollama_digest(model: str) -> str | None:
    """Отпечаток установленной модели или None, если такой модели в Ollama нет."""
    response = requests.get(OLLAMA_TAGS_URL, timeout=CHECK_TIMEOUT_SEC)
    response.raise_for_status()
    wanted = _with_tag(model)
    for item in response.json().get("models", []):
        if _with_tag(str(item.get("name", ""))) == wanted:
            return str(item.get("digest", "")).removeprefix("sha256:")
    return None


def check_ollama(model: str) -> ModelStatus:
    """Сравнивает отпечаток установленной модели с тем, что сейчас лежит на ollama.com."""
    title = f"Модель редактуры ({model})"

    def status(state: str, detail: str) -> ModelStatus:
        return ModelStatus(KIND_OLLAMA, model, title, state, detail)

    try:
        digest = _local_ollama_digest(model)
    except requests.RequestException:
        logger.warning("Не удалось спросить у Ollama список моделей", exc_info=True)
        return status(UNKNOWN, "Ollama не отвечает — она запущена?")

    if not digest:
        return status(UNKNOWN, f"не установлена в Ollama (команда для установки: ollama pull {model})")

    repo_and_tag = split_ollama_name(model)
    if repo_and_tag is None:
        return status(UNKNOWN, "проверка есть только для моделей с сайта ollama.com")

    repo, tag = repo_and_tag
    try:
        response = requests.get(
            OLLAMA_MANIFEST_URL.format(repo=repo, tag=tag),
            headers={"Accept": OLLAMA_MANIFEST_ACCEPT},
            timeout=CHECK_TIMEOUT_SEC,
        )
        response.raise_for_status()
    except requests.RequestException:
        logger.warning("Не удалось проверить обновление модели %s на ollama.com", model, exc_info=True)
        return status(UNKNOWN, "не удалось связаться с ollama.com (есть ли интернет?)")

    # Ollama называет модель по отпечатку её описания (манифеста) — сравниваем его.
    remote_digest = hashlib.sha256(response.content).hexdigest()
    if remote_digest == digest:
        return status(UP_TO_DATE, "установлена последняя версия")
    return status(UPDATE_AVAILABLE, "вышла новая версия")


def update_ollama(model: str) -> bool:
    """Скачивает новую версию модели через саму Ollama. True, если всё получилось."""
    logger.info("Скачиваю новую версию модели редактуры: %s", model)
    last_status = ""
    try:
        with requests.post(
            OLLAMA_PULL_URL,
            json={"model": model},
            stream=True,
            timeout=(CONNECT_TIMEOUT_SEC, DOWNLOAD_TIMEOUT_SEC),
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                data = json.loads(line)
                if data.get("error"):
                    logger.error("Ollama не смогла скачать модель %s: %s", model, data["error"])
                    return False
                if data.get("status") and data["status"] != last_status:
                    last_status = data["status"]
                    logger.info("Обновление %s: %s", model, last_status)
    except (requests.RequestException, ValueError, KeyError):
        logger.exception("Не удалось скачать новую версию модели %s", model)
        return False

    return last_status == "success"


# --- модель распознавания (Hugging Face) --------------------------------------


def _model_title(model_name: str) -> str:
    label = AVAILABLE_MODELS.get(model_name, model_name)
    short = label.split(" (")[0]  # из "Parakeet (русский + английский...)" берём "Parakeet"
    return f"Модель распознавания ({short})"


def _cache_folder(repo: str) -> Path:
    from huggingface_hub import constants

    return Path(constants.HF_HUB_CACHE) / ("models--" + repo.replace("/", "--"))


def _local_revision(repo: str) -> str | None:
    """Версия скачанной модели или None, если её ещё нет на диске."""
    ref_file = _cache_folder(repo) / "refs" / "main"
    try:
        return ref_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _local_files(repo: str, revision: str) -> list[str]:
    """Какие файлы модели уже скачаны — только их и обновляем, лишнего не качаем."""
    snapshot = _cache_folder(repo) / "snapshots" / revision
    if not snapshot.is_dir():
        return []
    return [path.relative_to(snapshot).as_posix() for path in snapshot.rglob("*") if path.is_file()]


def check_recognition(model_name: str) -> ModelStatus:
    """Сравнивает версию скачанной модели с последней версией на Hugging Face."""
    title = _model_title(model_name)

    def status(state: str, detail: str) -> ModelStatus:
        return ModelStatus(KIND_RECOGNITION, model_name, title, state, detail)

    repo = RECOGNITION_REPOS.get(model_name)
    if repo is None:
        return status(UNKNOWN, "для этой модели проверки нет")

    revision = _local_revision(repo)
    if revision is None:
        return status(UNKNOWN, "модель ещё не скачана")

    try:
        response = requests.get(HF_MODEL_URL.format(repo=repo), timeout=CHECK_TIMEOUT_SEC)
        response.raise_for_status()
        remote_revision = response.json().get("sha")
    except (requests.RequestException, ValueError):
        logger.warning("Не удалось проверить обновление модели %s", model_name, exc_info=True)
        return status(UNKNOWN, "не удалось связаться с huggingface.co (есть ли интернет?)")

    if not remote_revision:
        return status(UNKNOWN, "сайт не сообщил версию модели")
    if remote_revision == revision:
        return status(UP_TO_DATE, "установлена последняя версия")
    return status(UPDATE_AVAILABLE, "вышла новая версия")


def update_recognition(model_name: str) -> bool:
    """Докачивает новую версию модели распознавания. True, если всё получилось."""
    repo = RECOGNITION_REPOS.get(model_name)
    if repo is None:
        return False

    revision = _local_revision(repo)
    files = _local_files(repo, revision) if revision else []
    if not files:
        logger.warning("Не нашёл скачанных файлов модели %s, обновлять нечего", model_name)
        return False

    logger.info("Скачиваю новую версию модели распознавания: %s", model_name)
    try:
        from huggingface_hub import snapshot_download

        snapshot_download(repo, allow_patterns=files)
    except Exception:
        logger.exception("Не удалось скачать новую версию модели распознавания %s", model_name)
        return False

    logger.info("Модель распознавания %s обновлена", model_name)
    return True


# --- всё вместе ---------------------------------------------------------------


def check_all(app_settings: dict) -> list[ModelStatus]:
    """Проверяет обе модели: редактуры и распознавания."""
    return [
        check_ollama(app_settings["ollama_model"]),
        check_recognition(app_settings["recognition_model"]),
    ]


def update(status: ModelStatus) -> bool:
    """Скачивает обновление для одной модели."""
    if status.kind == KIND_OLLAMA:
        return update_ollama(status.name)
    return update_recognition(status.name)
