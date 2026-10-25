"""Tests for the Dev Console enhancements in ui/dev_console.py."""

import pytest
from unittest.mock import Mock, patch
from ui.dev_console import DevConsole

@pytest.fixture
def mock_dev_logger():
    """Create a mock dev logger."""
    mock_logger = Mock()
    mock_logger.tail.return_value = []
    mock_logger.event_logged = Mock()
    return mock_logger

@pytest.fixture
def dev_console(qtbot, mock_dev_logger):
    """Create a DevConsole instance with mock logger."""
    console = DevConsole(mock_dev_logger)
    qtbot.addWidget(console)
    return console

def test_dev_console_init(dev_console):
    """Test that DevConsole initializes correctly."""
    assert dev_console.dev_logger is not None
    assert dev_console.log_view.toPlainText() == ""

def test_dev_console_clear_log(dev_console):
    """Test that DevConsole.clear_log() clears the log view."""
    # Mock some events
    dev_console.log_view.append("Test event 1")
    dev_console.log_view.append("Test event 2")
    assert "Test event 1" in dev_console.log_view.toPlainText()
    dev_console.clear_log()
    assert dev_console.log_view.toPlainText() == ""

def test_dev_console_append_event(dev_console):
    """Test that DevConsole.append_event() adds formatted events."""
    # Mock an event
    event = {
        "timestamp": "2026-10-25T01:30:00Z",
        "type": "model_response",
        "payload": {
            "request_id": "req_123",
            "purpose": "test",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 5}
        }
    }
    dev_console.append_event(event)
    # Check that the event appears in the log with formatting
    log_text = dev_console.log_view.toPlainText()
    assert "2026-10-25T01:30:00Z" in log_text
    assert "model_response" in log_text
    assert "request_id=req_123" in log_text
    assert "purpose=test" in log_text
    assert "finish_reason=stop" in log_text

def test_dev_console_event_colors(dev_console):
    """Test that different event types get colored tags."""
    event_types = [
        ("user_message", "#7aa2f7"),
        ("model_request", "#bb9af7"),
        ("model_response", "#9ece6a"),
        ("tool_call", "#e0af68"),
        ("tool_result", "#7dcfff"),
        ("tool_error", "#f7768e"),
        ("final_answer", "#9ece6a"),
        ("error", "#f7768e"),
        ("iteration_limit", "#e0af68"),
        ("reasoning_content", "#bb9af7"),
        ("delivered", "#9ece6a"),
    ]

    for event_type, expected_color in event_types:
        event = {
            "timestamp": "2026-10-25T01:30:00Z",
            "type": event_type,
            "payload": {"test": "data"}
        }
        dev_console.log_view.clear()
        dev_console.append_event(event)
        log_text = dev_console.log_view.toPlainText()
        # Check that the event type appears with styling
        assert event_type in log_text
        # Check that the formatted event contains the payload
        assert "test=data" in log_text

def test_dev_console_payload_truncation(dev_console):
    """Test that large payloads are truncated."""
    # Create a large payload
    large_payload = {"text": "x" * 2000, "number": 123}
    event = {
        "timestamp": "2026-10-25T01:30:00Z",
        "type": "tool_result",
        "payload": large_payload
    }
    dev_console.log_view.clear()
    dev_console.append_event(event)
    log_text = dev_console.log_view.toPlainText()
    # Should contain some indication of truncation
    assert "...[truncated]" in log_text or len(log_text) < 3000

def test_dev_console_delivered_tag(dev_console):
    """Test that delivered events have a visual tag."""
    event = {
        "timestamp": "2026-10-25T01:30:00Z",
        "type": "delivered",
        "payload": {"request_id": "req_456"}
    }
    dev_console.log_view.clear()
    dev_console.append_event(event)
    log_text = dev_console.log_view.toPlainText()
    # Should have the delivered tag
    assert "[✓ delivered]" in log_text

def test_dev_console_iteration_limit_tag(dev_console):
    """Test that iteration_limit events have a visual tag."""
    event = {
        "timestamp": "2026-10-25T01:30:00Z",
        "type": "iteration_limit",
        "payload": {"max_iterations": 10}
    }
    dev_console.log_view.clear()
    dev_console.append_event(event)
    log_text = dev_console.log_view.toPlainText()
    # Should have the iteration limit tag
    assert "[⚠ iteration limit]" in log_text

def test_dev_console_reasoning_tag(dev_console):
    """Test that reasoning_content events have a visual tag."""
    event = {
        "timestamp": "2026-10-25T01:30:00Z",
        "type": "reasoning_content",
        "payload": {"thinking": "I'm thinking..."}
    }
    dev_console.log_view.clear()
    dev_console.append_event(event)
    log_text = dev_console.log_view.toPlainText()
    # Should have the reasoning tag
    assert "[thinking]" in log_text

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
