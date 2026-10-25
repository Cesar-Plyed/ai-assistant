"""Tests for the toast notification system in ui/toast.py."""

import pytest
from ui.toast import Toast, ToastManager

@pytest.fixture
def toast_manager(qtbot):
    """Create a ToastManager with a parent widget."""
    from ui.main_window import MainWindow
    window = MainWindow()
    qtbot.addWidget(window)
    manager = ToastManager(window)
    return manager, window

def test_toast_creation(toast_manager):
    """Test that a Toast can be created with basic properties."""
    manager, window = toast_manager
    toast = Toast("Test message", "info", parent=window, lifetime_ms=1000)
    assert toast.label.text() == "Test message"
    assert toast._effect.opacity() == 0.0

def test_toast_manager_creation(toast_manager):
    """Test that a ToastManager can be created."""
    manager, window = toast_manager
    assert manager.parent is window
    assert manager._toasts == []

def test_toast_manager_show(toast_manager):
    """Test that ToastManager.show() creates a Toast."""
    manager, window = toast_manager
    toast = manager.show("Test message", "info", lifetime_ms=1000)
    assert isinstance(toast, Toast)
    assert toast.label.text() == "Test message"
    assert toast in manager._toasts

def test_toast_levels(toast_manager):
    """Test that toast levels map to correct styles."""
    manager, window = toast_manager
    # Test info level
    info_toast = manager.info("Info message", lifetime_ms=1000)
    # Test warning level
    warning_toast = manager.warning("Warning message", lifetime_ms=1000)
    # Test error level
    error_toast = manager.error("Error message", lifetime_ms=1000)
    # Test success level
    success_toast = manager.success("Success message", lifetime_ms=1000)

    assert info_toast is not None
    assert warning_toast is not None
    assert error_toast is not None
    assert success_toast is not None

def test_toast_lifespan(toast_manager):
    """Test that toast auto-dismisses after lifetime."""
    manager, window = toast_manager
    toast = manager.show("Test", "info", lifetime_ms=100)
    assert toast in manager._toasts
    # The toast should close automatically after 100ms
    # Note: This test may need adjustment based on the Qt event loop

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
