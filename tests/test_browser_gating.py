"""Page reading must be blocked before any Playwright/browser work happens."""

import pytest

import config
from core.tools import browser_automation


def test_page_reading_disabled(monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "enable_browser_automation", True)
    monkeypatch.setitem(config.SETTINGS, "enable_browser_page_reading", False)

    def fail_if_touched():
        pytest.fail("Playwright/browser was touched while page reading was disabled")

    monkeypatch.setattr(browser_automation, "_get_page", fail_if_touched)

    assert browser_automation.browser_read_page() == browser_automation._PAGE_READING_DISABLED
    assert (
        browser_automation.browser_list_interactive_elements()
        == browser_automation._PAGE_READING_DISABLED
    )


def test_browser_exceptions_are_reported_with_the_error_prefix():
    @browser_automation._tool
    def explode():
        raise RuntimeError("boom")

    assert explode().startswith("Error:")


def test_browser_automation_disabled_returns_blocked(monkeypatch):
    monkeypatch.setitem(config.SETTINGS, "enable_browser_automation", False)

    @browser_automation._tool
    def anything():
        return "ok"

    assert anything().startswith("BLOCKED:")
