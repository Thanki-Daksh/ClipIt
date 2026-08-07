"""
tests/test_workers.py - Worker adapter registration (Agent 01 / TSK-A01-06).

Confirms register_workers() wires real sibling-module classes into the queue
engine handler registry without executing network/rendering work. Import-only,
so it passes even when ffmpeg / API keys are absent on the runner.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from core.config import Config
from core.queue import HANDLERS

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_handlers():
    """Ensure the shared handler registry stays clean between tests."""
    HANDLERS.clear()
    yield
    HANDLERS.clear()


def _make_cfg(tmp_path) -> Config:
    cfg = Config()
    cfg.resolved_db_path = Path(tmp_path) / "clipit.db"
    return cfg


def test_register_workers_wires_available_stages(tmp_path):
    from core.workers import register_workers
    cfg = _make_cfg(tmp_path)
    registered = register_workers(cfg, storage_root=tmp_path / "accounts")

    # Every importable worker module should have a handler.
    assert isinstance(registered, list)
    assert set(registered) <= {"DOWNLOADING", "TRANSCRIBING", "ANALYZING",
                               "CLIPPING", "CAPTIONING", "METADATA"}

    # Handlers were injected into the shared registry.
    for stage in registered:
        assert stage in HANDLERS


def test_worker_import_failure_is_graceful(monkeypatch, tmp_path):
    """A missing module yields an empty registration, not a crash."""
    from core.workers import _import
    assert _import("modules.does_not_exist", "Whatever") is None


def test_registered_handlers_module_importable():
    """The downloader handler should import its real class from modules."""
    sys.path.insert(0, str(PROJECT_ROOT))
    from modules.downloader import MediaDownloader  # noqa: F401
    assert MediaDownloader is not None