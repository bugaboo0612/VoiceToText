"""Окно настроек (tkinter). Открывается из меню значка в трее."""
import logging
import tkinter as tk
from tkinter import messagebox, ttk

import requests
import sounddevice as sd

from voicetocode import autostart, hotkey, settings
from voicetocode.recognizer import AVAILABLE_MODELS

logger = logging.getLogger(__name__)

STYLE_LABELS = {
    "raw": "Без обработки",
    "normal": "Обычный",
    "polite": "Вежливый",
    "professional": "Профессиональный",
}
MODE_LABELS = {
    "hold": "Удержание",
    "toggle": "Переключение",
}

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"  # не "localhost": на Windows его резолвинг иногда занимает 2+ секунды
DEFAULT_MIC_LABEL = "Системный по умолчанию"


def _list_microphones() -> list[str]:
    """Названия микрофонов, есть в системе (без повторов — одно и то же
    устройство часто видно сразу в нескольких звуковых системах Windows)."""
    names: list[str] = []
    try:
        for device in sd.query_devices():
            name = device.get("name")
            if device.get("max_input_channels", 0) > 0 and name not in names:
                names.append(name)
    except Exception:
        logger.warning("Не удалось получить список микрофонов", exc_info=True)
    return names


def _list_ollama_models() -> list[str]:
    try:
        response = requests.get(OLLAMA_TAGS_URL, timeout=3)
        response.raise_for_status()
        return [m["name"] for m in response.json().get("models", [])]
    except requests.RequestException:
        logger.warning("Не удалось получить список моделей Ollama (она запущена?)", exc_info=True)
        return []


class SettingsWindow:
    """Одно окно настроек, создаётся один раз и переиспользуется (show/hide)."""

    def __init__(
        self, root: tk.Tk, app_settings: dict, hotkey_listener, recorder, on_saved, on_recognition_model_changed
    ) -> None:
        self.root = root
        self.app_settings = app_settings
        self.hotkey_listener = hotkey_listener
        self.recorder = recorder
        self.on_saved = on_saved
        self.on_recognition_model_changed = on_recognition_model_changed

        self.window: tk.Toplevel | None = None
        self._capture_listener = None
        self._captured_modifiers: set = set()
        self._captured_main_vk = None

    def open(self) -> None:
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify()
            self.window.lift()
            return
        self._build_window()

    def refresh(self) -> None:
        """Подтягивает стиль и режим клавиши, если их изменили извне (меню трея)."""
        if self.window is None or not self.window.winfo_exists():
            return
        self.mode_var.set(self.app_settings["hotkey_mode"])
        self.style_var.set(self.app_settings["style"])

    def _build_window(self) -> None:
        self.window = tk.Toplevel(self.root)
        self.window.title("VoiceToCode — настройки")
        self.window.resizable(False, False)
        self.window.protocol("WM_DELETE_WINDOW", self._close)

        pad = {"padx": 10, "pady": 6}

        # --- Горячая клавиша ---
        hotkey_frame = ttk.LabelFrame(self.window, text="Горячая клавиша")
        hotkey_frame.pack(fill="x", **pad)
        modifiers, main_vk = hotkey.combo_from_settings(self.app_settings["hotkey_vks"])
        self._captured_modifiers, self._captured_main_vk = modifiers, main_vk
        self.hotkey_label = ttk.Label(hotkey_frame, text=hotkey.combo_name(modifiers, main_vk), width=20)
        self.hotkey_label.pack(side="left", padx=10, pady=8)
        self.hotkey_button = ttk.Button(hotkey_frame, text="Изменить", command=self._start_capture)
        self.hotkey_button.pack(side="left", padx=10, pady=8)

        # --- Режим клавиши ---
        mode_frame = ttk.LabelFrame(self.window, text="Режим клавиши")
        mode_frame.pack(fill="x", **pad)
        self.mode_var = tk.StringVar(value=self.app_settings["hotkey_mode"])
        for key, label in MODE_LABELS.items():
            ttk.Radiobutton(mode_frame, text=label, value=key, variable=self.mode_var).pack(
                side="left", padx=10, pady=4
            )

        # --- Стиль по умолчанию ---
        style_frame = ttk.LabelFrame(self.window, text="Стиль по умолчанию")
        style_frame.pack(fill="x", **pad)
        self.style_var = tk.StringVar(value=self.app_settings["style"])
        for key, label in STYLE_LABELS.items():
            ttk.Radiobutton(style_frame, text=label, value=key, variable=self.style_var).pack(
                anchor="w", padx=10, pady=2
            )

        # --- Микрофон ---
        mic_frame = ttk.LabelFrame(self.window, text="Микрофон")
        mic_frame.pack(fill="x", **pad)
        mic_names = _list_microphones()
        current_device = self.app_settings.get("microphone")
        current_label = current_device if current_device in mic_names else DEFAULT_MIC_LABEL
        self.mic_var = tk.StringVar(value=current_label)
        mic_box = ttk.Combobox(
            mic_frame,
            textvariable=self.mic_var,
            values=[DEFAULT_MIC_LABEL] + mic_names,
            state="readonly",
            width=40,
        )
        mic_box.pack(padx=10, pady=6, fill="x")

        # --- Модель распознавания ---
        recognition_frame = ttk.LabelFrame(self.window, text="Модель распознавания")
        recognition_frame.pack(fill="x", **pad)
        self._recognition_labels = list(AVAILABLE_MODELS.values())
        self._recognition_ids_by_label = {label: model_id for model_id, label in AVAILABLE_MODELS.items()}
        current_recognition_label = AVAILABLE_MODELS[self.app_settings["recognition_model"]]
        self.recognition_var = tk.StringVar(value=current_recognition_label)
        ttk.Combobox(
            recognition_frame,
            textvariable=self.recognition_var,
            values=self._recognition_labels,
            state="readonly",
            width=45,
        ).pack(padx=10, pady=6, fill="x")

        # --- Модель Ollama ---
        model_frame = ttk.LabelFrame(self.window, text="Модель Ollama")
        model_frame.pack(fill="x", **pad)
        models = _list_ollama_models()
        self.model_var = tk.StringVar(value=self.app_settings["ollama_model"])
        model_box = ttk.Combobox(model_frame, textvariable=self.model_var, values=models, width=40)
        if not models:
            model_box.configure(state="normal")
            ttk.Label(model_frame, text="(Ollama не отвечает — список моделей пуст)").pack(
                padx=10, anchor="w"
            )
        model_box.pack(padx=10, pady=6, fill="x")

        # --- Звук ---
        self.sound_var = tk.BooleanVar(value=self.app_settings["sound_enabled"])
        ttk.Checkbutton(self.window, text="Звуковой сигнал при записи", variable=self.sound_var).pack(
            anchor="w", padx=16, pady=6
        )

        # --- Автозапуск ---
        self.autostart_var = tk.BooleanVar(value=autostart.is_enabled())
        ttk.Checkbutton(
            self.window, text="Запускать вместе с Windows", variable=self.autostart_var
        ).pack(anchor="w", padx=16, pady=(0, 6))

        # --- Кнопки ---
        buttons_frame = ttk.Frame(self.window)
        buttons_frame.pack(fill="x", padx=10, pady=10)
        ttk.Button(buttons_frame, text="Сохранить", command=self._save).pack(side="right", padx=4)
        ttk.Button(buttons_frame, text="Закрыть", command=self._close).pack(side="right", padx=4)

    def _start_capture(self) -> None:
        if self._capture_listener is not None:
            return
        self.hotkey_label.configure(text="Нажмите нужное сочетание…")
        self.hotkey_button.configure(state="disabled")

        def on_captured(modifiers: set, main_vk) -> None:
            self.root.after(0, self._finish_capture, modifiers, main_vk)

        self._capture_listener = hotkey.capture_combo(on_captured)

    def _finish_capture(self, modifiers: set, main_vk) -> None:
        self._capture_listener = None
        self.hotkey_button.configure(state="normal")
        if main_vk is None:
            messagebox.showwarning(
                "VoiceToCode", "Нужно нажать хотя бы одну обычную клавишу (не только Ctrl/Alt/Shift)."
            )
            self.hotkey_label.configure(text=hotkey.combo_name(self._captured_modifiers, self._captured_main_vk))
            return
        self._captured_modifiers, self._captured_main_vk = modifiers, main_vk
        self.hotkey_label.configure(text=hotkey.combo_name(modifiers, main_vk))

    def _save(self) -> None:
        if self._capture_listener is not None:
            messagebox.showinfo("VoiceToCode", "Сначала закончите смену горячей клавиши.")
            return

        mic_choice = self.mic_var.get()
        mic_name = None if mic_choice == DEFAULT_MIC_LABEL else mic_choice

        self.app_settings["hotkey_mode"] = self.mode_var.get()
        self.app_settings["style"] = self.style_var.get()
        self.app_settings["hotkey_vks"] = sorted(self._captured_modifiers) + (
            [self._captured_main_vk] if self._captured_main_vk is not None else []
        )
        self.app_settings["microphone"] = mic_name
        self.app_settings["ollama_model"] = self.model_var.get().strip() or settings.DEFAULTS["ollama_model"]
        self.app_settings["sound_enabled"] = bool(self.sound_var.get())

        new_recognition_model = self._recognition_ids_by_label[self.recognition_var.get()]
        recognition_model_changed = new_recognition_model != self.app_settings["recognition_model"]
        self.app_settings["recognition_model"] = new_recognition_model

        settings.save(self.app_settings)

        if recognition_model_changed:
            self.on_recognition_model_changed(new_recognition_model)

        want_autostart = bool(self.autostart_var.get())
        if want_autostart != autostart.is_enabled():
            ok = autostart.enable() if want_autostart else autostart.disable()
            if not ok:
                messagebox.showwarning("VoiceToCode", "Не удалось изменить автозапуск с Windows.")

        self.hotkey_listener.mode = self.app_settings["hotkey_mode"]
        self.hotkey_listener.set_hotkey(self._captured_modifiers, self._captured_main_vk)
        self.recorder.device_name = mic_name

        if self.on_saved:
            self.on_saved()

        messagebox.showinfo("VoiceToCode", "Настройки сохранены.")
        self._close()

    def _close(self) -> None:
        if self._capture_listener is not None:
            self._capture_listener.stop()
            self._capture_listener = None
        if self.window is not None:
            self.window.withdraw()
