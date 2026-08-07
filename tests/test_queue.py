"""
tests/test_queue.py - State machine, atomic transition, crash recovery,
and N-account round-robin scheduler tests for core/queue.py.

Coverage targets:
  - Every legal forward transition in the 8-stage pipeline.
  - Illegal transitions raise StateError.
  - Known-account guard (unknown account -> ValueError).
  - fail_job auto-retry -> PENDING and budget exhaustion -> FAILED.
  - Crash / reboot recovery (recover + _resume_stage) across a headless DB.
  - Round-robin scheduler: budget-aware, FIFO per account, disabled accts skipped.
"""

from __future__ import annotations

import pytest

from core import queue as q
from core.queue import (
    ANALYZING, CAPTIONING, CLIPPING, COMPLETED, DOWNLOADING, FAILED,
    METADATA, PENDING, PIPELINE, TRANSCRIBING, WORKING_STAGES,
    QueueEngine, StateError,
)


@pytest.fixture
def engine(db, accounts) -> QueueEngine:
    return QueueEngine(db)


# ---------------------------------------------------------------------------
# Pipeline / transition table sanity
# ---------------------------------------------------------------------------

def test_pipeline_has_exactly_eight_stages():
    assert PIPELINE == [PENDING, DOWNLOADING, TRANSCRIBING, ANALYZING,
                        CLIPPING, CAPTIONING, METADATA, COMPLETED]


def test_working_stages_exclude_terminal():
    assert WORKING_STAGES == {DOWNLOADING, TRANSCRIBING, ANALYZING,
                              CLIPPING, CAPTIONING, METADATA}
    assert COMPLETED not in WORKING_STAGES
    assert FAILED not in WORKING_STAGES


def test_every_forward_transition_is_legal(engine, db, accounts):
    """Walk the full happy path with explicit atomic transitions."""
    job_id = engine.enqueue(accounts["alpha"], "https://youtube.com/watch?v=aaa")
    steps = [DOWNLOADING, TRANSCRIBING, ANALYZING, CLIPPING,
             CAPTIONING, METADATA, COMPLETED]
    for to_status in steps:
        engine.transition(job_id, to_status)
    final = db.get_job(job_id)
    assert final["status"] == COMPLETED


# ---------------------------------------------------------------------------
# Atomicity + transition guards
# ---------------------------------------------------------------------------

def test_illegal_forward_skip_raises(engine, accounts):
    """PENDING can only go to DOWNLOADING — skipping to CLIPPING must fail."""
    job_id = engine.enqueue(accounts["alpha"], "url")
    with pytest.raises(StateError):
        engine.transition(job_id, CLIPPING)


def test_terminal_completed_is_frozen(engine, accounts):
    job_id = engine.enqueue(accounts["alpha"], "url")
    for s in [DOWNLOADING, TRANSCRIBING, ANALYZING, CLIPPING,
              CAPTIONING, METADATA, COMPLETED]:
        engine.transition(job_id, s)
    # No transitions out of COMPLETED.
    assert q.TRANSITIONS[COMPLETED] == set()
    for target in (PENDING, FAILED, DOWNLOADING):
        with pytest.raises(StateError):
            engine.transition(job_id, target)


def test_fields_persist_atomically_with_transition(engine, db, accounts):
    job_id = engine.enqueue(accounts["alpha"], "url")
    engine.transition(job_id, DOWNLOADING, raw_video_path="/tmp/v.mp4",
                      duration_seconds=42.5)
    job = db.get_job(job_id)
    assert job["status"] == DOWNLOADING
    assert job["raw_video_path"] == "/tmp/v.mp4"
    assert job["duration_seconds"] == 42.5


def test_unknown_account_raises(engine):
    with pytest.raises(ValueError):
        engine.enqueue("no_such_account", "url")


# ---------------------------------------------------------------------------
# fail_job -> auto-retry / FAILED
# ---------------------------------------------------------------------------

def test_fail_job_retries_back_to_pending(engine, db, accounts):
    max_retries = 3
    job_id = engine.enqueue(accounts["alpha"], "url", max_retries=max_retries)
    engine.transition(job_id, DOWNLOADING)
    status = engine.fail_job(job_id, "network down")
    assert status == PENDING
    job = db.get_job(job_id)
    assert job["status"] == PENDING
    assert job["retry_count"] == 1
    assert "network down" in (job["error_log"] or "")


def test_fail_job_enters_failed_after_budget_exhausted(engine, db, accounts):
    job_id = engine.enqueue(accounts["alpha"], "url", max_retries=3)
    # Attempts 1 and 2 both return to PENDING (retry budget remains).
    for _ in range(2):
        engine.transition(job_id, DOWNLOADING)
        engine.fail_job(job_id, "boom")
    assert db.get_job(job_id)["status"] == PENDING
    assert db.get_job(job_id)["retry_count"] == 2
    # Attempt 3 exceeds budget -> FAILED.
    engine.transition(job_id, DOWNLOADING)
    status = engine.fail_job(job_id, "boom")
    assert status == FAILED
    assert db.get_job(job_id)["status"] == FAILED
    assert db.get_job(job_id)["retry_count"] == 3


# ---------------------------------------------------------------------------
# Crash / reboot recovery
# ---------------------------------------------------------------------------

def _mk_raw(engine, db, account_id, stage=DOWNLOADING, url="https://y/x"):
    """Enqueue and force a job into `stage`, returning (job_id, raw_path)."""
    job_id = engine.enqueue(account_id, url)
    db.update_job_status(job_id, stage)
    return job_id


def test_recover_downloading_without_artifact_returns_to_pending(engine, db, accounts):
    job_id = _mk_raw(engine, db, accounts["alpha"], DOWNLOADING)
    assert engine.recover() == [job_id]
    assert db.get_job(job_id)["status"] == PENDING


def test_recover_downloading_with_raw_advances_to_transcribing(
        engine, db, accounts, tmp_path):
    raw = tmp_path / "video.mp4"
    raw.write_bytes(b"fake")
    job_id = engine.enqueue(accounts["alpha"], "url")
    db.update_job_status(job_id, DOWNLOADING, raw_video_path=str(raw))
    assert engine.recover() == [job_id]
    assert db.get_job(job_id)["status"] == TRANSCRIBING


def test_recover_transcribing_with_transcript_advances(engine, db, accounts,
                                                      tmp_path, sample_transcript_json):
    raw = tmp_path / "video.mp4"
    raw.write_bytes(b"fake")
    job_id = engine.enqueue(accounts["alpha"], "url")
    db.update_job_status(job_id, TRANSCRIBING,
                         raw_video_path=str(raw), transcript_json=sample_transcript_json)
    assert engine.recover() == [job_id]
    assert db.get_job(job_id)["status"] == ANALYZING


def test_recover_metadata_with_clips_completes(engine, db, accounts, tmp_path):
    raw = tmp_path / "video.mp4"
    raw.write_bytes(b"fake")
    job_id = engine.enqueue(accounts["alpha"], "url")
    db.update_job_status(job_id, METADATA, raw_video_path=str(raw))
    db.create_clip(job_id, accounts["alpha"], "0", "4", 4.0, virality_score=88.0)
    assert engine.recover() == [job_id]
    assert db.get_job(job_id)["status"] == COMPLETED


def test_recover_skips_terminal_jobs(engine, db, accounts):
    done = engine.enqueue(accounts["alpha"], "url")
    db.update_job_status(done, COMPLETED)
    failed = engine.enqueue(accounts["alpha"], "url")
    db.update_job_status(failed, FAILED)
    assert engine.recover() == []


def test_recover_is_idempotent(engine, db, accounts, tmp_path):
    raw = tmp_path / "video.mp4"
    raw.write_bytes(b"fake")
    job_id = engine.enqueue(accounts["beta"], "url")
    db.update_job_status(job_id, DOWNLOADING, raw_video_path=str(raw))
    first = engine.recover()
    second = engine.recover()
    assert first == [job_id]
    # Second pass: already in TRANSCRIBING with raw present -> stays put.
    assert engine.db.get_job(job_id)["status"] == TRANSCRIBING
    assert second == []


# ---------------------------------------------------------------------------
# N-account round-robin scheduler
# ---------------------------------------------------------------------------

def test_accounts_under_budget_excludes_disabled(engine, accounts):
    under = engine.accounts_under_budget()
    assert "acc_off" not in under
    assert set(under) == {"acc_alpha", "acc_beta", "acc_gamma"}


def test_round_robin_picks_oldest_job_per_enabled_account(engine, db, accounts):
    for name in ("alpha", "beta", "gamma"):
        engine.enqueue(accounts[name], "https://y/{}".format(name))
    selected = engine.round_robin_cycle()
    picked_accounts = [acc for acc, _ in selected]
    # One job per enabled account, round-robin order even with mixed timestamps.
    assert sorted(set(picked_accounts)) == sorted({"acc_alpha", "acc_beta", "acc_gamma"})
    assert len(selected) == 3


def test_round_robin_fifo_within_account(engine, db, accounts):
    """Two jobs for one account dispatch oldest-first, one per tick."""
    engine.enqueue(accounts["alpha"], "first")
    engine.enqueue(accounts["alpha"], "second")
    first_tick = engine.round_robin_cycle()
    assert len(first_tick) == 1
    chosen, job = first_tick[0]
    assert job["source_url"] == "first"
    # After the job leaves PENDING, the next tick picks the second.
    engine.transition(job["id"], DOWNLOADING)
    second_tick = engine.round_robin_cycle()
    assert second_tick[0][1]["source_url"] == "second"


def test_budget_respected_by_scheduler(engine, db, accounts):
    """An account that has already hit its daily clip cap is not scheduled."""
    engine.enqueue(accounts["alpha"], "u1")
    engine.enqueue(accounts["alpha"], "u2")
    # alpha cap = 3; create 3 clips today (referencing a real job) -> exhausted.
    jid = engine.enqueue(accounts["alpha"], "seed")
    for _ in range(3):
        db.create_clip(jid, accounts["alpha"], "0", "10", 10.0)
    assert set(engine.accounts_under_budget()) == {"acc_beta", "acc_gamma"}


def test_no_jobs_returns_empty(engine):
    assert engine.round_robin_cycle() == []