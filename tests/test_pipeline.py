"""
tests/test_pipeline.py - End-to-end multi-account pipeline test.

Drives the real QueueEngine (core/queue.py) from enqueue -> COMPLETED across
multiple accounts in one scheduler run, using lightweight mock stage handlers
(registered via register_handler) that simulate each worker stage. Verifies:
  - the whole 8-stage state machine advances correctly,
  - N-account round-robin dispatches jobs for every enabled account,
  - daily clip budget is enforced across the run,
  - handler failures roll the job back to PENDING (retry) or FAILED (exhausted),
  - a crash mid-run is recovered and the pipeline resumes to COMPLETED.
"""

from __future__ import annotations

import json

import pytest

from core import queue as q
from core.queue import COMPLETED, DOWNLOADING, FAILED, PENDING, QueueEngine


# ---------------------------------------------------------------------------
# Mock stage handlers that simulate worker modules (Agents 02 & 03).
# They return payload dicts that QueueEngine._extract_fields maps onto the job.
# ---------------------------------------------------------------------------

def _make_handlers(tmp_path, *, error_stage=None, fail_always=False):
    """Register handlers for every working stage.

    - error_stage: the stage whose handler returns (False, ...) -> retry/fail.
    - fail_always: every handler returns failure (budget-exhaustion tests).
    """
    q.HANDLERS.clear()
    ok = lambda stage: not (error_stage == stage) and not fail_always  # noqa: E731

    q.register_handler(
        q.DOWNLOADING,
        lambda job, db: (ok(q.DOWNLOADING), {
            "raw_video_path": str(tmp_path / "raw.mp4"),
            "duration_seconds": 30.0,
        }),
    )
    q.register_handler(
        q.TRANSCRIBING,
        lambda job, db: (ok(q.TRANSCRIBING),
                         {"transcript_json": json.dumps({"text": "sample"})}),
    )
    q.register_handler(
        q.ANALYZING,
        lambda job, db: (ok(q.ANALYZING),
                         {"transcript_json": json.dumps({"summary": "ok", "clips": []})}),
    )
    q.register_handler(
        q.CLIPPING,
        lambda job, db: (ok(q.CLIPPING), {"video_path": str(tmp_path / "clip.mp4")}),
    )
    q.register_handler(
        q.CAPTIONING,
        lambda job, db: (ok(q.CAPTIONING), {"caption_path": str(tmp_path / "cap.txt")}),
    )
    q.register_handler(
        q.METADATA,
        lambda job, db: (ok(q.METADATA),
                         {"title": "Clip", "description": "desc", "hashtags": "#clip"}),
    )


@pytest.fixture
def clean_handlers():
    """Ensure no leftover handlers leak between tests."""
    q.HANDLERS.clear()
    yield
    q.HANDLERS.clear()


def _drive_to_completion(engine: QueueEngine, job_id: str) -> str:
    """Run the job until the engine parks it (terminal or unhandled)."""
    job = engine.db.get_job(job_id)
    status = job["status"]
    # Dispatch: a PENDING job must first be claimed (PENDING -> DOWNLOADING)
    # before the engine's working-stage loop will pick it up.
    if status == PENDING:
        engine.transition(job_id, q.DOWNLOADING)
        status = q.DOWNLOADING
    # run_job executes while status is a working stage; loop until stable.
    for _ in range(10):
        if status not in q.WORKING_STAGES:
            break
        status = engine.run_job(engine.db.get_job(job_id))
    return status


# ---------------------------------------------------------------------------
# End-to-end happy path
# ---------------------------------------------------------------------------

def test_full_pipeline_completes_single_account(db, accounts, clean_handlers, tmp_path):
    _make_handlers(tmp_path)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["alpha"], "https://e2e/1")

    final_status = _drive_to_completion(engine, job_id)
    assert final_status == COMPLETED
    assert db.get_job(job_id)["status"] == COMPLETED
    assert db.get_job(job_id)["raw_video_path"].endswith("raw.mp4")


def test_multi_account_round_robin_run(db, accounts, clean_handlers, tmp_path):
    """Enqueue one job per (enabled) account and drive them all to COMPLETED."""
    _make_handlers(tmp_path)
    engine = QueueEngine(db)
    ids = {}
    for name in ("alpha", "beta", "gamma"):
        ids[name] = engine.enqueue(accounts[name], f"https://e2e/{name}")
    # Disabled account enqueued too, but never dispatched to a worker.
    off_id = engine.enqueue(accounts["off"], "https://e2e/off")

    selected = engine.round_robin_cycle()
    assert len(selected) == 3  # disabled account excluded
    picked_accounts = {acc for acc, _ in selected}
    assert "acc_off" not in picked_accounts

    # Drive every dispatched job to completion.
    for _, job in selected:
        _drive_to_completion(engine, job["id"])

    for name, job_id in ids.items():
        assert db.get_job(job_id)["status"] == COMPLETED
    # The disabled account's job was never started.
    assert db.get_job(off_id)["status"] == PENDING


def test_pipeline_respects_daily_budget(db, accounts, clean_handlers, tmp_path):
    """A job for an account at its daily clip budget is skipped this run."""
    _make_handlers(tmp_path)
    engine = QueueEngine(db)
    # Exhaust gamma's budget by creating clips today (referencing a real job).
    cap = int(db.get_account("acc_gamma")["max_daily_clips"])
    seed = engine.enqueue(accounts["gamma"], "https://e2e/seed")
    for _ in range(cap):
        db.create_clip(seed, "acc_gamma", "0", "10", 10.0)

    engine.enqueue(accounts["alpha"], "https://e2e/alpha")
    engine.enqueue(accounts["beta"], "https://e2e/beta")
    engine.enqueue(accounts["gamma"], "https://e2e/budget")
    selected = engine.round_robin_cycle()
    assert {acc for acc, _ in selected} == {"acc_alpha", "acc_beta"}
    assert "acc_gamma" not in {acc for acc, _ in selected}


def test_pipeline_failure_returns_to_pending_for_retry(
        db, accounts, clean_handlers, tmp_path):
    """A failing stage returns the job to PENDING (retry budget remains)."""
    _make_handlers(tmp_path, error_stage=q.DOWNLOADING)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["alpha"], "https://e2e/fail")

    status = _drive_to_completion(engine, job_id)
    assert status == PENDING
    assert db.get_job(job_id)["retry_count"] == 1


def test_pipeline_exhausts_retries_to_failed(db, accounts, clean_handlers, tmp_path):
    """Persistent failure exhausts the retry budget -> permanent FAILED."""
    _make_handlers(tmp_path, fail_always=True)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["alpha"], "https://e2e/fail2", max_retries=2)

    _drive_to_completion(engine, job_id)  # attempt 1 -> PENDING
    _drive_to_completion(engine, job_id)  # attempt 2 exceeds budget -> FAILED
    assert db.get_job(job_id)["status"] == FAILED
    assert db.get_job(job_id)["retry_count"] == 2


def test_crash_recovery_then_completion(db, accounts, clean_handlers, tmp_path):
    """Simulate a crash: job stuck mid-stage -> recover -> run -> COMPLETED."""
    _make_handlers(tmp_path)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["beta"], "https://e2e/crash")

    # Crash: job stuck in DOWNLOADING with no on-disk artifact.
    db.update_job_status(job_id, DOWNLOADING)
    resumed = engine.recover()
    assert resumed == [job_id]
    assert db.get_job(job_id)["status"] == PENDING  # resumed to start

    # Re-run through the pipeline to completion.
    final_status = _drive_to_completion(engine, job_id)
    assert final_status == COMPLETED


def test_register_handler_rejects_non_working_stage(clean_handlers):
    """Only working stages may have handlers registered."""
    with pytest.raises(ValueError):
        q.register_handler(COMPLETED, lambda job, db: (True, {}))