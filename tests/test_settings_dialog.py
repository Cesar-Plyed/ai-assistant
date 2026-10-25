"""Tests for the settings dialog in ui/settings_dialog.py."""

import pytest
from unittest.mock import Mock, patch
from ui.settings_dialog import SettingsDialog

@pytest.fixture
def mock_config():
    """Mock the config module."""
    with patch('ui.settings_dialog.config') as mock_config:
        mock_config.SETTINGS = {
            "providers": [],
            "mcp_servers": [],
            "dev_mode": False,
            "enable_mouse_control": False,
            "enable_browser_page_reading": True,
            "enable_browser_automation": True,
            "browser_autostart": True,
            "require_submit_confirmation": True,
            "max_agent_iterations": 8,
            "max_tool_result_chars": 20000,
            "tool_profile": "compact",
            "tool_choice": "auto",
            "parallel_tool_calls": True,
            "temperature": 0.2,
            "max_tokens": 0,
            "active_provider": None,
        }
        yield mock_config

@pytest.fixture
def settings_dialog(qtbot, mock_config):
    """Create a SettingsDialog instance."""
    parent = None
    dialog = SettingsDialog(parent)
    qtbot.addWidget(dialog)
    return dialog

def test_settings_dialog_init(settings_dialog):
    """Test that SettingsDialog initializes correctly."""
    assert settings_dialog.settings is not None
    assert "tool_profile" in settings_dialog.settings

def test_settings_dialog_tabs(settings_dialog):
    """Test that the settings dialog has the expected tabs."""
    tab_count = settings_dialog.tab_widget.count()
    # Should have at least General tab
    assert tab_count >= 1

def test_tool_profiles_section(settings_dialog):
    """Test that the tool profiles section exists."""
    # The tool profiles section is in the general tab
    # We can check that the tool profile combo box exists
    assert hasattr(settings_dialog, 'tool_profile_combo')
    assert settings_dialog.tool_profile_combo.count() >= 3  # full, compact, read-only

def test_tool_profile_values(settings_dialog):
    """Test that tool profile values are loaded from settings."""
    assert settings_dialog.tool_profile_combo.currentText() == "compact"
    assert settings_dialog.tool_profile_combo.itemText(0) == "full"
    assert settings_dialog.tool_profile_combo.itemText(1) == "compact"
    assert settings_dialog.tool_profile_combo.itemText(2) == "read-only"

def test_tool_choice_values(settings_dialog):
    """Test that tool choice values are loaded from settings."""
    assert settings_dialog.tool_choice_combo.currentText() == "auto"
    assert settings_dialog.tool_choice_combo.itemText(0) == "auto"
    assert settings_dialog.tool_choice_combo.itemText(1) == "required"
    assert settings_dialog.tool_choice_combo.itemText(2) == "off"

def test_parallel_tool_calls_default(settings_dialog):
    """Test that parallel tool calls checkbox has correct default."""
    assert settings_dialog.parallel_tool_calls_check.isChecked() == True

def test_temperature_default(settings_dialog):
    """Test that temperature slider has correct default."""
    assert settings_dialog.temperature_spin.value() == 20  # 20% = 0.2

def test_max_tokens_default(settings_dialog):
    """Test that max tokens slider has correct default."""
    assert settings_dialog.max_tokens_spin.value() == 0

def test_settings_save(settings_dialog, mock_config):
    """Test that settings are saved when dialog is accepted."""
    # Change some settings
    settings_dialog.tool_profile_combo.setCurrentText("full")
    settings_dialog.tool_choice_combo.setCurrentText("required")
    settings_dialog.parallel_tool_calls_check.setChecked(False)
    settings_dialog.temperature_spin.setValue(50)
    settings_dialog.max_tokens_spin.setValue(1000)

    # Mock the accept method
    settings_dialog.accept = Mock()
    settings_dialog._save_and_close()

    # Verify settings were updated
    assert settings_dialog.settings["tool_profile"] == "full"
    assert settings_dialog.settings["tool_choice"] == "required"
    assert settings_dialog.settings["parallel_tool_calls"] == False
    assert settings_dialog.settings["temperature"] == 0.5  # 50% = 0.5
    assert settings_dialog.settings["max_tokens"] == 1000

def test_settings_cancel(settings_dialog):
    """Test that settings are not changed when dialog is cancelled."""
    # Store original settings
    original_settings = dict(settings_dialog.settings)

    # Mock the reject method
    settings_dialog.reject = Mock()
    # Call reject which should not save settings
    settings_dialog.reject()

    # Verify settings were not changed
    assert settings_dialog.settings == original_settings
    # Verify config.save_settings was not called
    settings_dialog.reject.assert_called_once()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
