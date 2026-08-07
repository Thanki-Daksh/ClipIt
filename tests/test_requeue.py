"""
tests/test_requeue.py - Crash re-queue engine (Agent 01 / TSK-A01-08).

`requeue_stuck()` must reset every job parked in a mid-pipeline working stage
back to PENDING regardless of on-disk artifacts, while leaving PENDING,
COMPLETED and FAILED jobs untouched.
"""

from __future__ import annotations

import pytest

from core.queue import (
    ANALYZING, CAPTIONING, CLIPPING, COMPLETED, DOWNLOADING, FAILED,
    METADATA, PENDING, TRANSCRIBING, QueueEngine,
)


@pytest.fixture
def engine(db) -> QueueEngine:
    return QueueEngine(db)


def _force(db, job_id, stage, **fields):
    db.update_job_status(job_id, stage, **fields)


def test_requeue_resets_all_working_stages(engine, db, accounts):
    """Every mid-pipeline stage is reset to PENDING in one call."""
    ids = {}
    for name, stage in [("alpha", DOWNLOADING), ("beta", TRANSCRIBING),
                        ("gamma", ANALYZING), ("alpha", CLIPPING),
                        ("beta", CAPTIONING), ("gamma", METADATA)]:
        jid = engine.enqueue(accounts[name], "https://y/u")
        _force(db, jid, stage)
        ids[jid] = stage

    requeued = engine.requeue_stuck()
    assert len(requeued) == len(ids)
    for jid in ids:
        assert db.get_job(jid)["status"] == PENDING


def test_requeue_ignores_pending_and_terminal(engine, db, accounts):
    pending = engine.enqueue(accounts["alpha"], "u")
    done = engine.enqueue(accounts["beta"], "v")
    failed = engine.enqueue(accounts["gamma"], "w")
    _force(db, done, COMPLETED)
    _force(db, failed, FAILED)

    assert engine.requeue_stuck() == []
    assert db.get_job(pending)["status"] == PENDING
    assert db.get_job(done)["status"] == COMPLETED
    assert db.get_job(failed)["status"] == FAILED


def test_requeue_clear_error_flag(engine, db, accounts):
    jid = engine.enqueue(accounts["alpha"], "u")
    _force(db, jid, DOWNLOADING)
    db.update_job_status(jid, "DOWNLOADING", error_log="boom")
    assert db.get_job(jid)["error_log"] == "boom"

    engine.requeue_stuck(clear_error=True)
    assert db.get_job(jid)["status"] == PENDING
    assert db.get_job(jid)["error_log"] is None


def test_requeue_without_clear_keeps_error_log(engine, db, accounts):
    jid = engine.enqueue(accounts["alpha"], "u")
    _force(db, jid, ANALYZING)
    db.update_job_status(jid, "ANALYZING", error_log="stale")
    engine.requeue_stuck(clear_error=False)
    assert db.get_job(jid)["status"] == PENDING
    assert db.get_job(jid)["error_log"] == "stale"


def test_requeue_after_recover_combination(engine, db, accounts, tmp_path):
    """
    Distinguishes the two recovery paths:
    - recover(): artifact-aware, advances a job with a present raw video.
    - requeue_stuck(): force resets ANY job still in a working stage to PENDING
      (used to blow away partial/uncertain state), including ones recover()
      already advanced — it always wins for full restarts.
    """
    raw = tmp_path / "raw.mp4"
    raw.write_bytes(b"x")
    a = engine.enqueue(accounts["alpha"], "u")
    b = engine.enqueue(accounts["beta"], "v")
    for jid in (a, b):
        _force(db, jid, DOWNLOADING, raw_video_path=str(raw))

    # recover() advances job A (artifact-aware) -> TRANSCRIBING.
    engine.recover()
    assert db.get_job(a)["status"] == TRANSCRIBING
    assert db.get_job(b)["status"] == TRANSCRIBING

    # A full restart then force-resets every working job back to PENDING.
    requeued = engine.requeue_stuck(clear_error=True)
    assert a in requeued and b in requeued
    assert db.get_job(a)["status"] == PENDING
    assert db.get_job(b)["status"] == PENDING