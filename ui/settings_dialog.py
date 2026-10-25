"""
Settings dialog with six tabs:
  - Providers: add/edit/remove model providers (with presets), test connections,
    fetch live model ids, pick the active provider.
  - Agent: tool profile / choice, temperature, token and step limits.
  - Browser: browser automation and page-reading options.
  - Appearance: Dark / Light / System theme and reduced motion.
  - MCP: manage MCP servers (stdio or HTTP) and the tool-call timeout.
  - Advanced: Dev Mode and mouse/keyboard control.
"""

import uuid

from PySide6.QtCore import QStringListModel, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QCompleter,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import config
from ui import theme
from core.providers import PROVIDER_TYPES, check_provider_connection
from core.providers.model_catalog import cached_models, list_models, static_models
from core.providers.presets import PROVIDER_PRESETS, get_preset, provider_from_preset

_FONT_MONO = "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', monospace"

_MCP_TRANSPORTS = ("stdio", "http")


class ModelCombo(QComboBox):
    """Editable model-id combo with a case-insensitive "contains" completer.

    Exposes ``text()`` / ``setText()`` / ``setPlaceholderText()`` so it is a
    drop-in replacement for a ``QLineEdit``.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(self.model(), self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.setCompleter(completer)
        self.setAccessibleName("Model")

    def text(self) -> str:
        return self.currentText()

    def setText(self, value: str) -> None:
        self.setCurrentText(value or "")

    def setPlaceholderText(self, text: str) -> None:  # noqa: N802 (Qt naming)
        edit = self.lineEdit()
        if edit is not None:
            edit.setPlaceholderText(text)

    def set_choices(self, models: list[str]) -> None:
        current = self.currentText()
        self.blockSignals(True)
        self.clear()
        self.addItems(models)
        self.setCurrentText(current)
        self.blockSignals(False)


class ModelFetchWorker(QThread):
    """Loads a provider's model list off the GUI thread."""

    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, provider: dict, force: bool = False, parent=None):
        super().__init__(parent)
        self.provider = provider
        self.force = force

    def run(self):
        try:
            self.finished_ok.emit(list_models(self.provider, force_refresh=self.force))
        except RuntimeError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # never let a worker crash the app
            self.failed.emit(f"Could not fetch models: {exc}")


def _int_setting(value, default: int) -> int:
    """Coerce a user-editable setting without crashing the dialog."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamped_int_setting(value, default: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, _int_setting(value, default)))


def _parse_args(text: str) -> list[str]:
    """One argument per line; blank lines are ignored."""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _parse_pairs(text: str, separator: str) -> dict[str, str]:
    """Parse ``KEY=VALUE`` / ``Name: value`` lines, skipping malformed ones."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or separator not in stripped:
            continue
        key, value = stripped.split(separator, 1)
        key = key.strip()
        if key:
            pairs[key] = value.strip()
    return pairs


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(860, 680)
        self.settings = dict(config.SETTINGS)
        self.providers = [
            dict(provider)
            for provider in self.settings.get("providers", [])
            if isinstance(provider, dict)
        ]
        self.mcp_servers = [
            dict(server)
            for server in self.settings.get("mcp_servers", [])
            if isinstance(server, dict)
        ]


        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        self.tabs = QTabWidget()
        self.tab_widget = self.tabs
        self.providers_tab = self._build_providers_tab()
        self.mcp_tab = self._build_mcp_tab()
        self._build_general_widgets()
        self.agent_tab = self._build_agent_tab()
        self.browser_tab = self._build_browser_tab()
        self.appearance_tab = self._build_appearance_tab()
        self.advanced_tab = self._build_advanced_tab()
        self.tabs.addTab(self.providers_tab, "Providers")
        self.tabs.addTab(self.agent_tab, "Agent")
        self.tabs.addTab(self.browser_tab, "Browser")
        self.tabs.addTab(self.appearance_tab, "Appearance")
        self.tabs.addTab(self.mcp_tab, "MCP")
        self.tabs.addTab(self.advanced_tab, "Advanced")
        root.addWidget(self.tabs, 1)

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
        self._refresh_mcp_list()
        self._refresh_model_completer()

    # ------------------------------------------------------------------
    def _build_providers_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(QLabel("Model providers"))
        self.provider_list = QListWidget()
        self.provider_list.currentRowChanged.connect(self._load_selected_provider)
        left.addWidget(self.provider_list)

        list_buttons = QHBoxLayout()
        list_buttons.setSpacing(8)
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self._add_provider)
        self.preset_button = QPushButton("Add preset")
        self.preset_menu = QMenu(self.preset_button)
        for preset in PROVIDER_PRESETS:
            action = self.preset_menu.addAction(preset["label"])
            action.triggered.connect(
                lambda _checked=False, pid=preset["id"]: self._add_preset(pid)
            )
        self.preset_button.setMenu(self.preset_menu)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self._remove_provider)
        self.set_active_button = QPushButton("Set active")
        self.set_active_button.clicked.connect(self._set_active_provider)
        list_buttons.addWidget(self.add_button)
        list_buttons.addWidget(self.preset_button)
        list_buttons.addWidget(self.remove_button)
        list_buttons.addWidget(self.set_active_button)
        left.addLayout(list_buttons)

        self.active_label = QLabel()
        self.active_label.setProperty("muted", True)
        left.addWidget(self.active_label)

        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(8)

        self.label_field = QLineEdit()
        self.type_field = QComboBox()
        for value, text in PROVIDER_TYPES:
            self.type_field.addItem(text, value)
        self.base_url_field = QLineEdit()
        self.base_url_field.setPlaceholderText("http://localhost:1234/v1")
        self.api_key_field = QLineEdit()
        self.api_key_field.setEchoMode(QLineEdit.EchoMode.Password)
        self.model_field = ModelCombo()
        self.model_field.setPlaceholderText("Model id")
        self._model_completer_model = self.model_field.model()
        self.model_completer = self.model_field.completer()
        self._fetch_worker: ModelFetchWorker | None = None

        form.addRow("Label", self.label_field)
        form.addRow("Type", self.type_field)
        form.addRow("Base URL", self.base_url_field)
        form.addRow("API key", self.api_key_field)

        model_row = QHBoxLayout()
        model_row.setSpacing(8)
        model_row.addWidget(self.model_field, 1)
        self.fetch_models_button = QPushButton("Refresh models")
        self.fetch_models_button.clicked.connect(self._fetch_models_clicked)
        model_row.addWidget(self.fetch_models_button)
        form.addRow("Model", model_row)
        self.models_status = QLabel("")
        self.models_status.setWordWrap(True)
        self.models_status.setProperty("muted", True)
        form.addRow("", self.models_status)
        right.addLayout(form)

        self.type_field.currentIndexChanged.connect(self._refresh_model_completer)

        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        self.save_provider_button = QPushButton("Save provider")
        self.save_provider_button.clicked.connect(self._save_current_provider)
        self.test_button = QPushButton("Test connection")
        self.test_button.clicked.connect(self._test_connection)
        save_row.addWidget(self.save_provider_button)
        save_row.addWidget(self.test_button)
        right.addLayout(save_row)

        right.addStretch()
        body.addLayout(right, 3)
        layout.addLayout(body)
        return tab

    # --- MCP tab -------------------------------------------------------
    def _build_mcp_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(12)

        body = QHBoxLayout()
        body.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(QLabel("MCP servers"))
        self.mcp_list = QListWidget()
        self.mcp_list.currentRowChanged.connect(self._load_selected_mcp_server)
        left.addWidget(self.mcp_list)

        mcp_buttons = QHBoxLayout()
        mcp_buttons.setSpacing(8)
        self.mcp_add_button = QPushButton("Add")
        self.mcp_add_button.clicked.connect(self._add_mcp_server)
        self.mcp_remove_button = QPushButton("Remove")
        self.mcp_remove_button.clicked.connect(self._remove_mcp_server)
        self.mcp_set_enabled_button = QPushButton("Set enabled")
        self.mcp_set_enabled_button.clicked.connect(self._set_mcp_enabled)
        mcp_buttons.addWidget(self.mcp_add_button)
        mcp_buttons.addWidget(self.mcp_remove_button)
        mcp_buttons.addWidget(self.mcp_set_enabled_button)
        left.addLayout(mcp_buttons)
        body.addLayout(left, 2)

        right = QVBoxLayout()
        right.setSpacing(8)

        self._mcp_form = QFormLayout()
        self._mcp_form.setSpacing(8)

        self.mcp_id_field = QLineEdit()
        self.mcp_label_field = QLineEdit()
        self.mcp_transport_field = QComboBox()
        for transport in _MCP_TRANSPORTS:
            self.mcp_transport_field.addItem(transport, transport)
        self.mcp_enabled_check = QCheckBox("Enabled")
        self.mcp_enabled_check.setChecked(True)

        self.mcp_command_field = QLineEdit()
        self.mcp_command_field.setPlaceholderText("npx")
        self.mcp_args_field = QPlainTextEdit()
        self.mcp_args_field.setPlaceholderText("One argument per line")
        self.mcp_args_field.setFixedHeight(72)
        self.mcp_env_field = QPlainTextEdit()
        self.mcp_env_field.setPlaceholderText("KEY=VALUE per line")
        self.mcp_env_field.setFixedHeight(64)

        self.mcp_url_field = QLineEdit()
        self.mcp_url_field.setPlaceholderText("https://example.com/mcp")
        self.mcp_headers_field = QPlainTextEdit()
        self.mcp_headers_field.setPlaceholderText("Name: value per line")
        self.mcp_headers_field.setFixedHeight(64)

        self._mcp_form.addRow("ID", self.mcp_id_field)
        self._mcp_form.addRow("Label", self.mcp_label_field)
        self._mcp_form.addRow("Transport", self.mcp_transport_field)
        self._mcp_form.addRow(self.mcp_enabled_check)
        self._mcp_form.addRow("Command", self.mcp_command_field)
        self._mcp_form.addRow("Arguments", self.mcp_args_field)
        self._mcp_form.addRow("Environment", self.mcp_env_field)
        self._mcp_form.addRow("URL", self.mcp_url_field)
        self._mcp_form.addRow("Headers", self.mcp_headers_field)
        right.addLayout(self._mcp_form)

        self.mcp_transport_field.currentIndexChanged.connect(
            self._update_mcp_field_visibility
        )

        save_row = QHBoxLayout()
        save_row.setSpacing(8)
        self.mcp_save_button = QPushButton("Save server")
        self.mcp_save_button.clicked.connect(self._save_current_mcp_server)
        save_row.addWidget(self.mcp_save_button)
        save_row.addStretch()
        right.addLayout(save_row)

        right.addStretch()
        body.addLayout(right, 3)
        layout.addLayout(body)

        timeout_row = QHBoxLayout()
        timeout_row.setSpacing(8)
        timeout_row.addWidget(QLabel("Tool call timeout (seconds)"))
        self.mcp_timeout_spin = QSpinBox()
        self.mcp_timeout_spin.setRange(5, 600)
        self.mcp_timeout_spin.setValue(
            _clamped_int_setting(self.settings.get("mcp_call_timeout"), 60, 5, 600)
        )
        timeout_row.addWidget(self.mcp_timeout_spin)
        timeout_row.addStretch()
        layout.addLayout(timeout_row)

        self._update_mcp_field_visibility()
        return tab

    # --- General tab ---------------------------------------------------
    def _build_general_widgets(self) -> None:
        self.dev_mode_check = QCheckBox("Show Dev Mode panel (reasoning / tool-call log)")
        self.dev_mode_check.setChecked(self.settings.get("dev_mode", False))
        self.mouse_control_check = QCheckBox("Enable mouse/keyboard control tools (use with caution)")
        self.mouse_control_check.setChecked(self.settings.get("enable_mouse_control", False))
        self.browser_reading_check = QCheckBox(
            "Enable web page reading (browser_read_page / browser_list_interactive_elements)"
        )
        self.browser_reading_check.setChecked(
            self.settings.get("enable_browser_page_reading", True)
        )
        self.browser_auto_check = QCheckBox(
            "Enable browser automation (click / type / read pages in the browser)"
        )
        self.browser_auto_check.setChecked(
            self.settings.get("enable_browser_automation", True)
        )
        self.browser_autostart_check = QCheckBox(
            "Auto-start the debug browser (Brave/Chromium) when needed"
        )
        self.browser_autostart_check.setChecked(
            self.settings.get("browser_autostart", True)
        )
        self.submit_confirm_check = QCheckBox(
            "Require confirmation before clicking Apply / Submit buttons"
        )
        self.submit_confirm_check.setChecked(
            self.settings.get("require_submit_confirmation", True)
        )
        self.max_iterations_spin = QSpinBox()
        self.max_iterations_spin.setRange(1, 30)
        self.max_iterations_spin.setValue(
            _int_setting(self.settings.get("max_agent_iterations"), 8)
        )
        self.max_tool_chars_spin = QSpinBox()
        self.max_tool_chars_spin.setRange(1000, 200000)
        self.max_tool_chars_spin.setSingleStep(1000)
        self.max_tool_chars_spin.setValue(
            _int_setting(self.settings.get("max_tool_result_chars"), 20000)
        )

        self.theme_combo = QComboBox()
        for value, label in (("dark", "Dark"), ("light", "Light"), ("system", "System")):
            self.theme_combo.addItem(label, value)
        idx = self.theme_combo.findData(str(self.settings.get("theme", "dark")))
        self.theme_combo.setCurrentIndex(max(idx, 0))
        self.theme_combo.setAccessibleName("Theme")
        self.reduce_motion_check = QCheckBox("Reduce motion (no slide/fade animations)")
        self.reduce_motion_check.setChecked(bool(self.settings.get("reduce_motion", False)))

    @staticmethod
    def _tab_layout(tab: QWidget) -> QVBoxLayout:
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 16, 12, 12)
        return layout

    def _build_agent_tab(self) -> QWidget:
        tab = QWidget()
        layout = self._tab_layout(tab)
        limits = QFormLayout()
        limits.setSpacing(12)
        limits.addRow("Max reasoning steps per message", self.max_iterations_spin)
        limits.addRow("Max characters returned by a tool", self.max_tool_chars_spin)
        layout.addLayout(limits)
        # ── Tool profiles ──────────────────────────────────────────────
        profile_group = QGroupBox("Tool calling")
        profile_layout = QFormLayout(profile_group)
        profile_layout.setSpacing(10)

        self.tool_profile_combo = QComboBox()
        self.tool_profile_combo.addItems(["full", "compact", "read-only"])
        self.tool_profile_combo.setCurrentText(str(self.settings.get("tool_profile", "compact")))
        profile_layout.addRow("Tool profile", self.tool_profile_combo)

        self.tool_choice_combo = QComboBox()
        self.tool_choice_combo.addItems(["auto", "required", "off"])
        self.tool_choice_combo.setCurrentText(str(self.settings.get("tool_choice", "auto")))
        profile_layout.addRow("Tool choice", self.tool_choice_combo)

        self.parallel_tool_calls_check = QCheckBox("Allow parallel tool calls")
        self.parallel_tool_calls_check.setChecked(bool(self.settings.get("parallel_tool_calls", True)))
        profile_layout.addRow("", self.parallel_tool_calls_check)

        self.temperature_spin = QSpinBox()
        self.temperature_spin.setRange(0, 100)
        self.temperature_spin.setSingleStep(1)
        self.temperature_spin.setSuffix("%")
        self.temperature_spin.setValue(int(float(self.settings.get("temperature", 0.2)) * 100))
        profile_layout.addRow("Temperature", self.temperature_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(0, 128000)
        self.max_tokens_spin.setSpecialValueText("default")
        self.max_tokens_spin.setValue(
            _clamped_int_setting(self.settings.get("max_tokens"), 0, 0, 128000)
        )
        profile_layout.addRow("Max tokens (0 = provider default)", self.max_tokens_spin)

        layout.addWidget(profile_group)
        layout.addStretch()
        return tab

    def _build_browser_tab(self) -> QWidget:
        tab = QWidget()
        layout = self._tab_layout(tab)
        form = QFormLayout()
        form.setSpacing(12)
        form.addRow(self.browser_reading_check)
        form.addRow(self.browser_auto_check)
        form.addRow(self.browser_autostart_check)
        form.addRow(self.submit_confirm_check)
        layout.addLayout(form)
        layout.addStretch()
        return tab

    def _build_appearance_tab(self) -> QWidget:
        tab = QWidget()
        layout = self._tab_layout(tab)
        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Theme", self.theme_combo)
        form.addRow(self.reduce_motion_check)
        layout.addLayout(form)
        layout.addStretch()
        return tab

    def _build_advanced_tab(self) -> QWidget:
        tab = QWidget()
        layout = self._tab_layout(tab)
        form = QFormLayout()
        form.setSpacing(12)
        form.addRow(self.dev_mode_check)
        form.addRow(self.mouse_control_check)
        layout.addLayout(form)
        layout.addStretch()
        return tab

    # --- Provider list / editor ---------------------------------------
    def _refresh_provider_list(self):
        self.provider_list.clear()
        for provider in self.providers:
            marker = (
                " (active)"
                if provider.get("id") == self.settings.get("active_provider")
                else ""
            )
            item = QListWidgetItem(f"{provider.get('label', 'Unnamed')}{marker}")
            self.provider_list.addItem(item)
        self.active_label.setText(f"Active: {self._active_provider_label()}")

    def _active_provider_label(self) -> str:
        for provider in self.providers:
            if provider.get("id") == self.settings.get("active_provider"):
                return provider.get("label", "Unnamed")
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
        self._refresh_model_completer()

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

    def _add_preset(self, preset_id: str):
        preset = get_preset(preset_id)
        if preset is None:
            return
        existing = {p.get("id") for p in self.providers}
        provider = provider_from_preset(preset, existing)
        self.providers.append(provider)
        self._refresh_provider_list()
        self.provider_list.setCurrentRow(len(self.providers) - 1)
        # Fetch the model list right away when a key is already available
        # (env var) or the provider is local and needs none.
        if preset.get("local") or config.resolve_api_key(provider):
            self._fetch_models_clicked(force=False)

    def _remove_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            return
        removed = self.providers.pop(row)
        if (
            self.settings.get("active_provider") == removed.get("id")
            and self.providers
        ):
            self.settings["active_provider"] = self.providers[0].get("id")
        self._refresh_provider_list()

    def _set_active_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            return
        self.settings["active_provider"] = self.providers[row].get("id")
        self._refresh_provider_list()

    def _refresh_model_completer(self, *_args):
        """Static suggestions for the current type, plus any cached live list."""
        provider = self._provider_from_form(self.provider_list.currentRow()
                                            if self.provider_list.currentRow() >= 0 else None)
        values = cached_models(provider) or static_models(self.type_field.currentData())
        current = self.model_field.text().strip()
        if current and current not in values:
            values = [current, *values]
        self.model_field.set_choices(list(values))

    def _set_model_choices(self, models: list[str]):
        values = [str(model).strip() for model in models]
        values = [model for model in values if model]
        current = self.model_field.text().strip()
        if current and current not in values:
            values.insert(0, current)
        self.model_field.set_choices(values)

    def _provider_from_form(self, row: int | None = None) -> dict:
        """Build a provider dict from the editor, like ``_test_connection``."""
        if row is not None and 0 <= row < len(self.providers):
            provider = dict(self.providers[row])
        else:
            provider = {"id": ""}
        provider["label"] = (
            self.label_field.text().strip() or provider.get("label", "Unnamed")
        )
        provider["type"] = self.type_field.currentData()
        provider["base_url"] = self.base_url_field.text().strip()
        provider["api_key"] = self.api_key_field.text()
        provider["model"] = self.model_field.text().strip()
        return provider

    def _test_connection(self):
        row = self.provider_list.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No provider selected", "Select a provider first.")
            return
        provider = self._provider_from_form(row)

        try:
            check_provider_connection(provider)
            QMessageBox.information(
                self,
                "Connection OK",
                f"Successfully connected to '{provider['label']}'.",
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Connection failed",
                f"Could not connect to '{provider['label']}':\n{e}",
            )

    def _fetch_models_clicked(self, _checked: bool = False, force: bool = True):
        if self._fetch_worker is not None and self._fetch_worker.isRunning():
            return
        row = self.provider_list.currentRow()
        provider = self._provider_from_form(row if row >= 0 else None)
        self.fetch_models_button.setEnabled(False)
        self.models_status.setStyleSheet("")
        self.models_status.setText("Loading models…")
        worker = ModelFetchWorker(provider, force=force, parent=self)
        worker.finished_ok.connect(self._on_models_loaded)
        worker.failed.connect(self._on_models_failed)
        worker.finished.connect(lambda: self.fetch_models_button.setEnabled(True))
        self._fetch_worker = worker
        worker.start()

    def _on_models_loaded(self, models: list):
        self._set_model_choices(models)
        self.models_status.setText(f"{len(models)} model(s) available.")

    def _on_models_failed(self, message: str):
        # Inline error (no modal dialog); colour comes from the active theme.
        self.models_status.setStyleSheet(f"color: {theme.tokens()['error']};")
        self.models_status.setText(message)

    def done(self, result):  # make sure the worker is gone before the dialog dies
        worker = self._fetch_worker
        if worker is not None and worker.isRunning():
            worker.wait(3000)
        super().done(result)

    def _commit_form_to_provider(self, row: int):
        """Copy the current editor field values into self.providers[row]."""
        if row < 0 or row >= len(self.providers):
            return
        provider = self.providers[row]
        provider["label"] = (
            self.label_field.text().strip() or provider.get("label", "Unnamed")
        )
        provider["type"] = self.type_field.currentData()
        provider["base_url"] = self.base_url_field.text().strip()
        provider["api_key"] = self.api_key_field.text()
        provider["model"] = self.model_field.text().strip()

    def _save_current_provider(self):
        row = self.provider_list.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "No provider selected", "Select or add a provider first."
            )
            return
        self._commit_form_to_provider(row)
        self._refresh_provider_list()
        self.provider_list.setCurrentRow(row)

    # --- MCP list / editor --------------------------------------------
    def _refresh_mcp_list(self):
        current = self.mcp_list.currentRow()
        self.mcp_list.blockSignals(True)
        self.mcp_list.clear()
        for server in self.mcp_servers:
            label = str(server.get("label") or server.get("id") or "MCP server")
            transport = str(server.get("transport") or "stdio")
            state = "" if server.get("enabled", True) else " (disabled)"
            self.mcp_list.addItem(QListWidgetItem(f"{label} [{transport}]{state}"))
        self.mcp_list.blockSignals(False)

        if self.mcp_servers:
            row = min(max(current, 0), len(self.mcp_servers) - 1)
            self.mcp_list.setCurrentRow(row)
        else:
            self._clear_mcp_form()

    def _clear_mcp_form(self):
        self.mcp_id_field.clear()
        self.mcp_label_field.clear()
        self.mcp_transport_field.setCurrentIndex(0)
        self.mcp_enabled_check.setChecked(True)
        self.mcp_command_field.clear()
        self.mcp_args_field.clear()
        self.mcp_env_field.clear()
        self.mcp_url_field.clear()
        self.mcp_headers_field.clear()
        self._update_mcp_field_visibility()

    def _load_selected_mcp_server(self, row: int):
        if row < 0 or row >= len(self.mcp_servers):
            return
        server = self.mcp_servers[row]
        self.mcp_id_field.setText(str(server.get("id", "")))
        self.mcp_label_field.setText(str(server.get("label", "")))

        index = self.mcp_transport_field.findData(server.get("transport", "stdio"))
        self.mcp_transport_field.setCurrentIndex(index if index >= 0 else 0)

        self.mcp_enabled_check.setChecked(bool(server.get("enabled", True)))
        self.mcp_command_field.setText(str(server.get("command", "")))

        args = server.get("args") or []
        self.mcp_args_field.setPlainText("\n".join(str(arg) for arg in args))

        env = server.get("env") or {}
        self.mcp_env_field.setPlainText(
            "\n".join(f"{key}={value}" for key, value in env.items())
        )

        self.mcp_url_field.setText(str(server.get("url", "")))

        headers = server.get("headers") or {}
        self.mcp_headers_field.setPlainText(
            "\n".join(f"{key}: {value}" for key, value in headers.items())
        )
        self._update_mcp_field_visibility()

    def _update_mcp_field_visibility(self, *_args):
        transport = self.mcp_transport_field.currentData() or "stdio"
        is_stdio = transport == "stdio"
        for widget in (self.mcp_command_field, self.mcp_args_field, self.mcp_env_field):
            self._set_mcp_row_visible(widget, is_stdio)
        for widget in (self.mcp_url_field, self.mcp_headers_field):
            self._set_mcp_row_visible(widget, not is_stdio)

    def _set_mcp_row_visible(self, widget: QWidget, visible: bool):
        widget.setVisible(visible)
        label = self._mcp_form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _add_mcp_server(self):
        new_server = {
            "id": f"mcp_{uuid.uuid4().hex[:8]}",
            "label": "New MCP server",
            "transport": "stdio",
            "command": "",
            "args": [],
            "env": {},
            "url": "",
            "headers": {},
            "enabled": True,
        }
        self.mcp_servers.append(new_server)
        self._refresh_mcp_list()
        self.mcp_list.setCurrentRow(len(self.mcp_servers) - 1)

    def _remove_mcp_server(self):
        row = self.mcp_list.currentRow()
        if row < 0 or row >= len(self.mcp_servers):
            return
        self.mcp_servers.pop(row)
        self._refresh_mcp_list()

    def _set_mcp_enabled(self):
        row = self.mcp_list.currentRow()
        if row < 0 or row >= len(self.mcp_servers):
            return
        self.mcp_servers[row]["enabled"] = True
        self.mcp_enabled_check.setChecked(True)
        self._refresh_mcp_list()

    def _commit_mcp_form(self, row: int):
        """Copy the current MCP editor values into self.mcp_servers[row]."""
        if row < 0 or row >= len(self.mcp_servers):
            return
        existing = self.mcp_servers[row]
        transport = self.mcp_transport_field.currentData()
        self.mcp_servers[row] = {
            "id": (
                self.mcp_id_field.text().strip()
                or existing.get("id")
                or f"mcp_{uuid.uuid4().hex[:8]}"
            ),
            "label": (
                self.mcp_label_field.text().strip()
                or existing.get("label")
                or "New MCP server"
            ),
            "transport": transport if transport in _MCP_TRANSPORTS else "stdio",
            "command": self.mcp_command_field.text().strip(),
            "args": _parse_args(self.mcp_args_field.toPlainText()),
            "env": _parse_pairs(self.mcp_env_field.toPlainText(), "="),
            "url": self.mcp_url_field.text().strip(),
            "headers": _parse_pairs(self.mcp_headers_field.toPlainText(), ":"),
            "enabled": self.mcp_enabled_check.isChecked(),
        }

    def _save_current_mcp_server(self):
        row = self.mcp_list.currentRow()
        if row < 0:
            QMessageBox.warning(
                self, "No server selected", "Select or add an MCP server first."
            )
            return
        self._commit_mcp_form(row)
        self._refresh_mcp_list()
        self.mcp_list.setCurrentRow(row)

    # --- Persistence ---------------------------------------------------
    def _save_and_close(self):
        # Commit whatever is currently in the editors, even if the per-item
        # "Save provider" / "Save server" buttons were never clicked.
        self._commit_form_to_provider(self.provider_list.currentRow())
        self._commit_mcp_form(self.mcp_list.currentRow())

        self.settings["providers"] = self.providers
        self.settings["mcp_servers"] = self.mcp_servers
        self.settings["mcp_call_timeout"] = self.mcp_timeout_spin.value()
        self.settings["dev_mode"] = self.dev_mode_check.isChecked()
        self.settings["enable_mouse_control"] = self.mouse_control_check.isChecked()
        self.settings["enable_browser_page_reading"] = (
            self.browser_reading_check.isChecked()
        )
        self.settings["enable_browser_automation"] = self.browser_auto_check.isChecked()
        self.settings["browser_autostart"] = self.browser_autostart_check.isChecked()
        self.settings["require_submit_confirmation"] = (
            self.submit_confirm_check.isChecked()
        )
        self.settings["max_agent_iterations"] = self.max_iterations_spin.value()
        self.settings["max_tool_result_chars"] = self.max_tool_chars_spin.value()
        self.settings["theme"] = self.theme_combo.currentData()
        self.settings["reduce_motion"] = self.reduce_motion_check.isChecked()
        self.settings["tool_profile"] = self.tool_profile_combo.currentText()
        self.settings["tool_choice"] = self.tool_choice_combo.currentText()
        self.settings["parallel_tool_calls"] = self.parallel_tool_calls_check.isChecked()
        self.settings["temperature"] = self.temperature_spin.value() / 100.0
        max_tokens = self.max_tokens_spin.value()
        self.settings["max_tokens"] = max_tokens if max_tokens > 0 else None
        config.save_settings(self.settings)
        config.reload_settings()
        self.accept()
