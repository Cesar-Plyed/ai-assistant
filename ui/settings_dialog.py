"""
Settings dialog.

Lets the user:
  - Add/edit/remove model providers (LM Studio, Ollama, any OpenAI-compatible
    cloud API paid or free, or native Gemini) and pick which one is active.
  - Test the connection to a provider before relying on it.
  - Toggle Dev Mode, mouse/keyboard control, and browser page reading.
"""

import uuid

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget, QListWidgetItem,
    QLineEdit, QComboBox, QPushButton, QLabel, QCheckBox, QSpinBox, QMessageBox, QWidget,
)

import config


PROVIDER_TYPES = [("openai_compatible", "OpenAI-compatible (LM Studio / Ollama / cloud API)"), ("gemini", "Google Gemini (native)")]


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(640, 520)
        self.settings = dict(config.SETTINGS)
        self.providers = [dict(p) for p in self.settings.get("providers", [])]

        root = QVBoxLayout(self)

        # --- Provider list + editor -----------------------------------
        body = QHBoxLayout()

        left = QVBoxLayout()
        left.addWidget(QLabel("Model providers"))
        self.provider_list = QListWidget()
        self.provider_list.currentRowChanged.connect(self._load_selected_provider)
        left.addWidget(self.provider_list)

        list_buttons = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._add_provider)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_provider)
        self.set_active_button = QPushButton("Set active")
        self.set_active_button.clicked.connect(self._set_active_provider)
        list_buttons.addWidget(self.add_button)
        list_buttons.addWidget(self.remove_button)
        list_buttons.addWidget(self.set_active_button)
        left.addLayout(list_buttons)

        self.active_label = QLabel()
        left.addWidget(self.active_label)

        body.addLayout(left, 2)

        right = QVBoxLayout()
        form = QFormLayout()
        self.label_field = QLineEdit()
        self.type_field = QComboBox()
        for value, text in PROVIDER_TYPES:
            self.type_field.addItem(text, value)
        self.base_url_field = QLineEdit()
        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_field = QLineEdit()

        form.addRow("Label", self.label_field)
        form.addRow("Type", self.type_field)
        form.addRow("Base URL", self.base_url_field)
        form.addRow("API key", self.api_key_field)
        form.addRow("Model", self.model_field)
        right.addLayout(form)

        save_row = QHBoxLayout()
        self.save_provider_button = QPushButton("Save provider")
        self.save_provider_button.clicked.connect(self._save_current_provider)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_connection)
        save_row.addWidget(self.save_provider_button)
        save_row.addWidget(self.test_button)
        right.addLayout(save_row)

        right.addStretch()
        body.addLayout(right, 3)
        root.addLayout(body)

        # --- General toggles ---------------------------------------------
        toggles = QFormLayout()
        self.dev_mode_check = QCheckBox("Show Dev Mode panel (reasoning / tool-call log)")
        self.dev_mode_check.setChecked(self.settings.get("dev_mode", False))
        self.mouse_control_check = QCheckBox("Enable mouse/keyboard control tools (use with caution)")
        self.mouse_control_check.setChecked(self.settings.get("enable_mouse_control", False))
        self.browser_reading_check = QCheckBox("Enable web page reading tool")
        self.browser_reading_check.setChecked(self.settings.get("enable_browser_page_reading", True))
        self.max_iterations_spin = QSpinBox()
        self.max_iterations_spin.setRange(1, 30)
        self.max_iterations_spin.setValue(self.settings.get("max_agent_iterations", 8))

        toggles.addRow(self.dev_mode_check)
        toggles.addRow(self.mouse_control_check)
        toggles.addRow(self.browser_reading_check)
        toggles.addRow("Max reasoning steps per message", self.max_iterations_spin)
        root.addLayout(toggles)

        # --- Dialog buttons -------------------------------------------
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.save_button = QPushButton("Save and close")
        self.save_button.clicked.connect(self._save_and_close)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.save_button)
        root.addLayout(bottom)

        self._refresh_provider_list()

    # ------------------------------------------------------------------
    def _refresh_provider_list(self):
        self.provider_list.clear()
        for provider in self.providers:
            marker = " (active)" if provider["id"] == self.settings.get("active_provider") else ""
            item = QListWidgetItem(f"{provider['label']}{marker}")
            self.provider_list.addItem(item)
        self.active_label.setText(f"Active: {self._active_provider_label()}")

    def _active_provider_label(self) -> str:
        for provider in self.providers:
            if provider["id"] == self.settings.get("active_provider"):
                return provider["label"]
        return "(none)"

    def _load_selected_provider(self, row: int):
        if row < 0 or row >= len(self.providers):
            return
        provider = self.providers[row]
        self.label_field.setText(provider.get("label", ""))
        index = self.type_field.findData(provider.get("type", "openai_compatible"))
        self.type_field.setCurrentIndex(max(index, 0))
        self.base_url_field.setText(provider.get("base_url", ""))
        self.api_key_field.setText(provider.get("api_key", ""))
        self.model_field.setText(provider.get("model", ""))

    def _add_provider(self):
        new_provider = {
            "id": f"custom_{uuid.uuid4().hex[:8]}",
            "label": "New provider",
            "type": "openai_compatible",
            "base_url": "http://localhost:1234/v1",
            "api_key": "",
            "model": "",
        }
        self.providers.append(new_provider)
        self._refresh_provider_list()
        self.provider_list.setCurrentRow(len(self.providers) - 1)

    def _remove_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            return
        removed = self.providers.pop(row)
        if self.settings.get("active_provider") == removed["id"] and self.providers:
            self.settings["active_provider"] = self.providers[0]["id"]
        self._refresh_provider_list()

    def _set_active_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            return
        self.settings["active_provider"] = self.providers[row]["id"]
        self._refresh_provider_list()

    def _test_connection(self):
        row = self.provider_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No provider selected", "Select a provider first.")
            return
        provider = dict(self.providers[row])
        provider["label"] = self.label_field.text().strip() or provider["label"]
        provider["type"] = self.type_field.currentData()
        provider["base_url"] = self.base_url_field.text().strip()
        provider["api_key"] = self.api_key_field.text()
        provider["model"] = self.model_field.text().strip()

        try:
            if provider["type"] == "gemini":
                from google import genai
                key = config.resolve_api_key(provider)
                if not key:
                    raise RuntimeError("No API key set.")
                client = genai.Client(api_key=key)
                client.models.list()
            else:
                from openai import OpenAI
                client = OpenAI(base_url=provider["base_url"] or None, api_key=config.resolve_api_key(provider) or "not-needed")
                client.models.list()
            QMessageBox.information(self, "Connection OK", f"Successfully connected to '{provider['label']}'.")
        except Exception as e:
            QMessageBox.critical(self, "Connection failed", f"Could not connect to '{provider['label']}':\n{e}")

    def _commit_form_to_provider(self, row: int):
        """Copy the current editor field values into self.providers[row]."""
        if row < 0 or row >= len(self.providers):
            return
        provider = self.providers[row]
        provider["label"]    = self.label_field.text().strip() or provider.get("label", "Unnamed")
        provider["type"]     = self.type_field.currentData()
        provider["base_url"] = self.base_url_field.text().strip()
        provider["api_key"]  = self.api_key_field.text()
        provider["model"]    = self.model_field.text().strip()


    def _save_current_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No provider selected", "Select or add a provider first.")
            return
        self._commit_form_to_provider(row)
        self._refresh_provider_list()
        self.provider_list.setCurrentRow(row)


    def _save_and_close(self):
        # Commit whatever is currently in the editor, even if "Save provider"
        # was never clicked.
        self._commit_form_to_provider(self.provider_list.currentRow())

        self.settings["providers"] = self.providers
        self.settings["dev_mode"] = self.dev_mode_check.isChecked()
        self.settings["enable_mouse_control"] = self.mouse_control_check.isChecked()
        self.settings["enable_browser_page_reading"] = self.browser_reading_check.isChecked()
        self.settings["max_agent_iterations"] = self.max_iterations_spin.value()
        config.save_settings(self.settings)
        config.reload_settings()
        self.accept()
