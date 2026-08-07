"""
tests/test_health.py - System healthcheck API (Agent 01 / TSK-A01-09).

Checks build_health_payload returns database, queue, disk and storage metrics
without raising, and that the FastAPI GET /health endpoint serves it.
"""

from __future__ import annotations

import pytest

from core.health import build_health_payload, create_health_app


def test_health_payload_has_sections(db, tmp_path):
    store_root = tmp_path / "accounts"
    payload = build_health_payload(db=db, storage_root=store_root)

    assert payload["status"] == "ok"
    assert payload["service"] == "clipit"
    assert "database" in payload and "queue" in payload and "storage" in payload

    assert payload["database"]["ok"] is True
    assert payload["database"]["journal_mode"] == "wal"
    assert payload["database"]["foreign_keys"] == 1

    assert "total_jobs" in payload["queue"]
    assert isinstance(payload["storage"]["per_account"], dict)
    assert "disk" in payload


def test_health_payload_no_db_does_not_raise():
    payload = build_health_payload(db=None)
    assert payload["database"]["ok"] is False
    assert payload["status"] == "ok"


def test_health_reports_job_counts(db, accounts):
    # seed one pending job
    from core.queue import QueueEngine
    q = QueueEngine(db)
    q.enqueue(accounts["alpha"], "https://y/u")
    payload = build_health_payload(db=db)
    assert payload["queue"]["pending"] == 1
    assert payload["queue"]["total_jobs"] == 1


def test_health_endpoint_route(db, tmp_path):
    from fastapi.testclient import TestClient
    app = create_health_app(db=db, storage_root=tmp_path / "accounts")
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "clipit"
    assert body["database"]["ok"] is True