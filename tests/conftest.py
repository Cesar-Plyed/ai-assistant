"""Shared pytest fixtures.

The Qt platform must be selected before any Qt module is imported, otherwise
pytest-qt may try to connect to a real display in headless environments.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

from core import memory  # noqa: E402


@pytest.fixture
def chats_dir(tmp_path, monkeypatch):
    """Redirect chat persistence to a throwaway directory."""
    monkeypatch.setattr(memory, "CHATS_DIR", tmp_path)
    return tmp_path
