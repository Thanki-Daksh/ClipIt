"""
ClipIt Job Queue State Machine Engine
-------------------------------------
8-stage pipeline: PENDING → DOWNLOADING → TRANSCRIBING → ANALYZING → CLIPPING
→ CAPTIONING → METADATA → COMPLETED. Any working stage may fail; failed jobs
auto-retry (up to max_retries) by returning to PENDING.

Crash recovery: on daemon restart, jobs stuck in a working stage are inspected
against on-disk artifacts and resumed from the earliest stage whose artifact
is missing (or returned to PENDING).

N-account round-robin scheduler: dispatches one job per enabled account per
tick, honoring each account's max_daily_clips budget.

Every state transition is atomic (single SQLite transaction) — zero partial
updates survive a crash.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from core.db import Database
from core.logger import get_logger

log = get_logger("queue")

# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

PENDING     = "PENDING"
DOWNLOADING = "DOWNLOADING"
TRANSCRIBING = "TRANSCRIBING"
ANALYZING   = "ANALYZING"
CLIPPING    = "CLIPPING"
CAPTIONING  = "CAPTIONING"
METADATA    = "METADATA"
COMPLETED   = "COMPLETED"
FAILED      = "FAILED"

PIPELINE = [PENDING, DOWNLOADING, TRANSCRIBING, ANALYZING,
            CLIPPING, CAPTIONING, METADATA, COMPLETED]

# Stages that do real work and may fail (terminal states excluded)
WORKING_STAGES = {DOWNLOADING, TRANSCRIBING, ANALYZING, CLIPPING, CAPTIONING, METADATA}
TERMINAL_STAGES = {COMPLETED, FAILED}

# Valid forward transitions: stage -> {allowed next stages}
TRANSITIONS: dict[str, set[str]] = {
    PENDING:      {DOWNLOADING},
    DOWNLOADING:  {TRANSCRIBING, FAILED},
    TRANSCRIBING: {ANALYZING, FAILED},
    ANALYZING:    {CLIPPING, FAILED},
    CLIPPING:     {CAPTIONING, FAILED},
    CAPTIONING:   {METADATA, FAILED},
    METADATA:     {COMPLETED, FAILED},
    FAILED:       {PENDING},          # auto-retry edge
    COMPLETED:    set(),
}

# Stage -> artifact field name whose *presence on disk* means the stage finished
STAGE_ARTIFACT: dict[str, str] = {
    DOWNLOADING:  "raw_video_path",
    TRANSCRIBING: "transcript_json",
    ANALYZING:    "transcript_json",  # analysis is stored back into transcript_json
    CLIPPING:     "raw_video_path",   # clips are children of the job; see _resume_stage
    CAPTIONING:   "raw_video_path",
    METADATA:     "raw_video_path",
}

# Handler registry: stage -> callable(job_row, db) -> (ok: bool, detail: Any)
Handler = Callable[[Any, Database], tuple[bool, Any]]
HANDLERS: dict[str, Handler] = {}


def register_handler(stage: str, fn: Handler) -> None:
    """Register a worker for a pipeline stage (used by Agent 02/03 modules)."""
    if stage not in WORKING_STAGES:
        raise ValueError(f"Cannot register handler for non-working stage '{stage}'")
    HANDLERS[stage] = fn
    log.debug("handler registered for %s", stage)


class StateError(Exception):
    """Raised when an illegal state transition is attempted."""


class QueueEngine:
    """Job queue state machine + recovery + round-robin scheduler."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(self, account_id: str, source_url: str, source_type: str = "youtube",
                title: Optional[str] = None, max_retries: Optional[int] = None) -> str:
        if self.db.get_account(account_id) is None:
            raise ValueError(f"Unknown account '{account_id}' — create it first")
        return self.db.create_job(
            account_id=account_id, source_url=source_url, source_type=source_type,
            title=title, max_retries=max_retries,
        )

    # ------------------------------------------------------------------
    # Atomic state transitions
    # ------------------------------------------------------------------

    def transition(self, job_id: str, to_status: str, **fields: Any) -> None:
        """
        Atomically move a job from its current status to `to_status`.
        Validates against TRANSITIONS; raises StateError on illegal moves.
        """
        job = self.db.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown job '{job_id}'")
        current = job["status"]
        allowed = TRANSITIONS.get(current, set())
        if to_status not in allowed:
            raise StateError(
                f"Illegal transition {current} -> {to_status} for job {job_id} "
                f"(allowed: {sorted(allowed)})"
            )
        # All fields that arrive are persisted in the same atomic update.
        self.db.update_job_status(job_id, to_status, **fields)
        self.db.log_event("INFO", f"{current} -> {to_status}", job_id=job_id,
                          account_id=job["account_id"],
                          data={"job_id": job_id, "from": current, "to": to_status})
        log.info("job %s: %s -> %s", job_id, current, to_status)

    def fail_job(self, job_id: str, error: str) -> str:
        """
        Record a stage failure. If retry budget remains, job returns to PENDING
        (auto-retry); otherwise it enters FAILED. Returns the resulting status.
        """
        job = self.db.get_job(job_id)
        if job is None:
            raise ValueError(f"Unknown job '{job_id}'")
        retry_count = int(job["retry_count"] or 0) + 1
        max_retries = int(job["max_retries"] or self.db.max_retries)
        log_line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] attempt {retry_count}: {error}"

        with self.db.transaction() as conn:
            if retry_count < max_retries:
                conn.execute(
                    "UPDATE jobs SET status='PENDING', retry_count=?, "
                    "error_log=COALESCE(error_log||'\n','')||?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (retry_count, log_line, job_id),
                )
                result = PENDING
            else:
                conn.execute(
                    "UPDATE jobs SET status='FAILED', retry_count=?, "
                    "error_log=COALESCE(error_log||'\n','')||?, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (retry_count, log_line, job_id),
                )
                result = FAILED

        self.db.log_event("ERROR" if result == FAILED else "WARNING",
                          f"job failed -> {result}", job_id=job_id,
                          account_id=job["account_id"], data={"error": error})
        log.warning("job %s failed (retry %s/%s) -> %s", job_id, retry_count,
                    max_retries, result)
        return result

    # ------------------------------------------------------------------
    # Crash / reboot recovery
    # ------------------------------------------------------------------

    def recover(self) -> list[str]:
        """
        Inspect every non-terminal job on startup and resume it from the
        earliest stage whose artifact is missing. Returns resumed job ids.
        """
        jobs = self.db.list_jobs()
        resumed: list[str] = []
        for job in jobs:
            if job["status"] in TERMINAL_STAGES:
                continue
            resume = self._resume_stage(job)
            if resume and resume != job["status"]:
                log.info("recovery: job %s %s -> %s", job["id"], job["status"], resume)
                self.db.update_job_status(job["id"], resume)
                self.db.log_event("WARNING", f"crash recovery: {job['status']} -> {resume}",
                                  job_id=job["id"], account_id=job["account_id"])
                resumed.append(job["id"])
            elif resume == job["status"]:
                # Already at the correct resume stage; leave it for the scheduler.
                log.info("recovery: job %s continues at %s", job["id"], resume)
        return resumed

    def _resume_stage(self, job) -> str:
        """Compute the earliest unfinished stage for a stuck job."""
        status = job["status"]
        if status == PENDING:
            return PENDING

        raw_path = job["raw_video_path"]
        has_raw = bool(raw_path) and Path(raw_path).exists()
        has_transcript = bool(job["transcript_json"])
        has_clips = bool(self.db.list_clips(job["id"]))

        if status == DOWNLOADING:
            return TRANSCRIBING if has_raw else PENDING
        if status == TRANSCRIBING:
            return ANALYZING if has_transcript else (TRANSCRIBING if has_raw else PENDING)
        if status == ANALYZING:
            return CLIPPING if has_transcript else (ANALYZING if has_raw else PENDING)
        if status == CLIPPING:
            return CAPTIONING if has_clips else (CLIPPING if has_raw else PENDING)
        if status == CAPTIONING:
            return METADATA if has_clips else (CAPTIONING if has_raw else PENDING)
        if status == METADATA:
            return COMPLETED if has_clips else (METADATA if has_raw else PENDING)
        return PENDING

    # ------------------------------------------------------------------
    # N-account round-robin scheduler
    # ------------------------------------------------------------------

    def accounts_under_budget(self) -> list[str]:
        """Enabled accounts that still have daily clip budget left."""
        result = []
        for acc in self.db.list_accounts(enabled_only=True):
            used = self.db.clips_created_today(acc["id"])
            if used < int(acc["max_daily_clips"] or 0):
                result.append(acc["id"])
            else:
                log.debug("account %s at daily clip budget (%s/%s)", acc["id"],
                          used, acc["max_daily_clips"])
        return result

    def next_job_for_account(self, account_id: str) -> Optional[Any]:
        """Oldest PENDING job for an account, or None."""
        jobs = self.db.pending_jobs_for_account(account_id)
        return jobs[0] if jobs else None

    def round_robin_cycle(self) -> list[tuple[str, Any]]:
        """
        One scheduler tick: for each enabled account with budget, claim its
        oldest PENDING job. Returns [(account_id, job_row), ...] in account
        order (round-robin across N accounts, FIFO within each account).
        """
        selected: list[tuple[str, Any]] = []
        for account_id in self.accounts_under_budget():
            job = self.next_job_for_account(account_id)
            if job:
                selected.append((account_id, job))
        if selected:
            log.info("scheduler tick: dispatching %s job(s) across %s account(s)",
                     len(selected), len({a for a, _ in selected}))
        return selected

    # ------------------------------------------------------------------
    # Execution loop helpers
    # ------------------------------------------------------------------

    def run_job(self, job) -> str:
        """
        Execute one job through the pipeline using registered handlers.
        Returns the final status after this run.
        """
        status = job["status"]
        account_id = job["account_id"]

        # PENDING jobs are claimed by moving them into the pipeline.
        if status == PENDING:
            self.transition(job["id"], DOWNLOADING)
            status = DOWNLOADING

        while status in WORKING_STAGES:
            handler = HANDLERS.get(status)
            if handler is None:
                log.warning("no handler registered for stage %s — job %s parked", status, job["id"])
                return status
            try:
                ok, detail = handler(job, self.db)
            except Exception as exc:  # worker bug → treat as stage failure
                log.exception("handler %s crashed for job %s", status, job["id"])
                return self.fail_job(job["id"], f"{type(exc).__name__}: {exc}")

            if not ok:
                return self.fail_job(job["id"], str(detail or "stage handler returned failure"))

            # advance to next pipeline stage
            next_stage = PIPELINE[PIPELINE.index(status) + 1]
            fields = self._extract_fields(status, detail)
            self.transition(job["id"], next_stage, **fields)
            status = next_stage
            job = self.db.get_job(job["id"])
            if job is None:
                return next_stage
            if next_stage == COMPLETED:
                self.db.log_event("INFO", "job completed", job_id=job["id"], account_id=account_id)
        return status

    # Columns that exist on the `jobs` table (transcript_json etc. are mapped
    # here; clip-level details live on the `clips` table, not `jobs`).
    _JOB_COLUMNS = {"raw_video_path", "audio_path", "transcript_json",
                    "duration_seconds", "title"}

    @staticmethod
    def _extract_fields(stage: str, detail: Any) -> dict:
        """Map a handler's return payload onto job columns for the next stage."""
        fields: dict[str, Any] = {}
        if not isinstance(detail, dict):
            return fields
        # whitelist to avoid writing stage artifacts onto non-existent job columns
        for key, val in detail.items():
            if key in QueueEngine._JOB_COLUMNS and val is not None:
                fields[key] = val
        return fields

    # ------------------------------------------------------------------
    # CLI convenience
    # ------------------------------------------------------------------

    def summarize(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in self.db.list_jobs():
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        return counts


__all__ = [
    "QueueEngine", "StateError", "PIPELINE", "WORKING_STAGES",
    "PENDING", "DOWNLOADING", "TRANSCRIBING", "ANALYZING", "CLIPPING",
    "CAPTIONING", "METADATA", "COMPLETED", "FAILED", "register_handler",
]
