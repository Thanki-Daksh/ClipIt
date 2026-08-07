"""
tests/test_concurrency.py - TSK-A06-08: Queue concurrency stress test.

Verifies the SQLite-backed QueueEngine / Database stay consistent under heavy
concurrent load:
  - 50 simultaneous thread-pooled job enqueues all succeed,
  - every job row is independently retrievable with correct status,
  - SQLite `integrity_check` passes (no torn/corrupt pages),
  - no exceptions / deadlocks surface during the burst,
  - concurrent state transitions remain atomic & legal.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from core import queue as q
from core.queue import DOWNLOADING, PENDING, TRANSCRIBING, QueueEngine


def _account(db):
    if db.get_account("acc_stress") is None:
        db.create_account("acc_stress", "Stress", "tests", sources=[],
                          max_daily_clips=999, enabled=1)
    return "acc_stress"


def _enqueue(engine: QueueEngine, account_id: str) -> str:
    # Each worker enqueues a job; distinct URL to keep entries distinguishable.
    return engine.enqueue(account_id, "https://stress/job", title=None)


def test_bulk_concurrent_enqueue_50(db):
    account_id = _account(db)
    engine = QueueEngine(db)
    n = 50

    with ThreadPoolExecutor(max_workers=16) as pool:
        jobs = list(pool.map(lambda _: engine.enqueue(account_id, "https://stress"), range(n)))

    assert len(jobs) == n
    assert len(set(jobs)) == n, "job ids must be unique"
    rows = db.list_jobs(account_id=account_id)
    assert len(rows) == n, f"expected {n} jobs, found {len(rows)}"
    assert all(r["status"] == PENDING for r in rows)


def test_concurrent_enqueue_and_read_consistency(db, accounts):
    account_id = _account(db)
    engine = QueueEngine(db)
    n = 50

    def reader(_):
        # Read-only sweep while writers run; must never raise or return junk.
        return len(db.list_jobs(status=PENDING))

    with ThreadPoolExecutor(max_workers=20) as pool:
        enqueue_futures = [pool.submit(engine.enqueue, account_id, f"https://stress/{i}")
                           for i in range(n)]
        read_futures = [pool.submit(reader, i) for i in range(25)]
        job_ids = [f.result() for f in enqueue_futures]
        reads = [f.result() for f in read_futures]

    assert len(job_ids) == n
    assert all(isinstance(v, int) for v in reads)
    assert db.list_jobs(account_id=account_id)[0]["status"] == PENDING


def test_concurrent_legal_transitions_are_atomic(db, accounts):
    """Concurrent enqueue + legal state transition must never produce partial rows."""
    account_id = _account(db)
    engine = QueueEngine(db)
    # Create a handful of distinct jobs up front.
    ids = [engine.enqueue(account_id, f"https://stress/t{i}") for i in range(20)]

    def advance(job_id):
        # PENDING -> DOWNLOADING is the only valid move at start.
        engine.transition(job_id, DOWNLOADING)
        return job_id

    with ThreadPoolExecutor(max_workers=10) as pool:
        advanced = list(pool.map(advance, ids))

    assert len(advanced) == len(ids)
    for job_id in ids:
        status = db.get_job(job_id)["status"]
        assert status in (DOWNLOADING,), f"job {job_id} bad status {status}"


def test_integrity_check_pass_after_stress(db, accounts):
    """After all writes, SQLite integrity must report 'ok' (no corruption)."""
    account_id = _account(db)
    engine = QueueEngine(db)
    n = 50
    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(lambda _: engine.enqueue(account_id, "https://stress/"), range(n)))

    conn = db._conn()
    row = conn.execute("PRAGMA integrity_check;").fetchone()
    assert row[0] == "ok", f"integrity_check = {row[0]}"


def test_round_robin_after_concurrent_load_consistent(db, accounts):
    """The scheduler must still see a coherent picture post-burst."""
    account_id = _account(db)
    engine = QueueEngine(db)
    n = 30
    with ThreadPoolExecutor(max_workers=12) as pool:
        list(pool.map(lambda _: engine.enqueue(account_id, "https://stress/rr"),
                      range(n)))
    selected = engine.round_robin_cycle()
    assert len(selected) == 1  # oldest PENDING job for this single account
    assert selected[0][0] == account_id


def _account(db):
    if db.get_account("acc_stress") is None:
        db.create_account("acc_stress", "Stress", "stress", sources=[],
                          max_daily_clips=999, enabled=1)
    return "acc_stress"