"""
tests/test_db_durability.py - production durability & atomicity guarantees.

Audits the Database layer for what "zero data loss" requires:
  - WAL journal + synchronous=FULL (fsynced COMMIT -> survives power loss)
  - foreign_keys enforced on every connection
  - atomic BEGIN IMMEDIATE transactions (all-or-nothing on exception)
  - a runtime guard against the non-reentrant write-lock deadlock
  - integrity/orphan detection and WAL checkpoint helpers
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from core.db import Database, SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Connection pragmas (durability configuration)
# ---------------------------------------------------------------------------

def test_default_synchronous_is_full(db):
    """Production default must fsync the WAL before COMMIT returns."""
    assert db._conn().execute("PRAGMA synchronous;").fetchone()[0] == 2


def test_journal_mode_wal(db):
    assert db._conn().execute("PRAGMA journal_mode;").fetchone()[0] == "wal"


def test_foreign_keys_enforced_on_connect(db):
    assert db._conn().execute("PRAGMA foreign_keys;").fetchone()[0] == 1


def test_busy_timeout_configured(db):
    assert db._conn().execute("PRAGMA busy_timeout;").fetchone()[0] == 10000


def test_sync_override_via_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPIT_DB_SYNCHRONOUS", "NORMAL")
    db = Database(tmp_path / "env.db")
    assert db._conn().execute("PRAGMA synchronous;").fetchone()[0] == 1


def test_sync_override_numeric_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPIT_DB_SYNCHRONOUS", "0")
    db = Database(tmp_path / "env0.db")
    assert db._conn().execute("PRAGMA synchronous;").fetchone()[0] == 0


def test_sync_override_via_arg_wins(tmp_path, monkeypatch):
    """Explicit constructor arg beats the environment."""
    monkeypatch.setenv("CLIPIT_DB_SYNCHRONOUS", "OFF")
    db = Database(tmp_path / "arg.db", synchronous="FULL")
    assert db._conn().execute("PRAGMA synchronous;").fetchone()[0] == 2


def test_invalid_sync_falls_back_to_full(tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPIT_DB_SYNCHRONOUS", "BOGUS")
    db = Database(tmp_path / "bad.db")
    assert db._conn().execute("PRAGMA synchronous;").fetchone()[0] == 2


# ---------------------------------------------------------------------------
# Atomic transactions
# ---------------------------------------------------------------------------

def test_transaction_rolls_back_on_exception(db):
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts (id, name, niche, sources_json, "
                "branding_preset_json, metadata_preset_json) "
                "VALUES ('acc_x', 'X', 'n', '[]', '{}', '{}')"
            )
            raise RuntimeError("boom")
    assert db.get_account("acc_x") is None


def test_transaction_all_or_nothing(db):
    """Two inserts in one tx: the first must vanish when the second fails."""
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts (id, name, niche, sources_json, "
                "branding_preset_json, metadata_preset_json) "
                "VALUES ('acc_y', 'Y', 'n', '[]', '{}', '{}')"
            )
            conn.execute(
                "INSERT INTO accounts (id, name, niche, sources_json, "
                "branding_preset_json, metadata_preset_json) "
                "VALUES ('acc_z', 'Z', 'n', '[]', '{}', '{}')"
            )
            raise RuntimeError("boom mid-tx")
    assert db.get_account("acc_y") is None
    assert db.get_account("acc_z") is None


def test_nested_transaction_raises_clear_error(db):
    """log_event() inside an open transaction() must raise, not deadlock."""
    with pytest.raises(RuntimeError, match="nested transaction"):
        with db.transaction() as conn:
            db.log_event("INFO", "should not hang")


def test_commit_persists_and_reopens(tmp_path):
    """A committed write must survive a full close/reopen of the DB."""
    p = tmp_path / "durable.db"
    db = Database(p)
    db.init_schema()
    db.create_account("acc_keep", "Keep", "n", sources=[])
    db.close()
    db2 = Database(p)
    db2.init_schema()
    assert db2.get_account("acc_keep") is not None
    db2.close()


def test_fk_cascade_delete_account_removes_all(db):
    db.create_account("acc_c", "C", "n", sources=[])
    jid = db.create_job("acc_c", "https://example.com/v", "url", "T")
    cid = db.create_clip(jid, "acc_c", "0", "5", 5.0)
    db.delete_account("acc_c")
    assert db.get_job(jid) is None
    assert db.list_clips() == []


# ---------------------------------------------------------------------------
# Integrity + checkpoint helpers
# ---------------------------------------------------------------------------

def test_check_integrity_clean(db):
    report = db.check_integrity()
    assert report["quick_check"] == "ok"
    assert report["orphan_clips_no_job"] == 0
    assert report["orphan_clips_no_account"] == 0


def test_check_integrity_detects_orphans(db):
    """Rows inserted with FK off (legacy/wiped DB) must be surfaced."""
    conn = sqlite3.connect(str(db.db_path))
    conn.execute("PRAGMA foreign_keys=OFF;")
    conn.execute(
        "INSERT INTO clips (id, job_id, account_id, start_time, end_time, "
        "duration_seconds) VALUES ('orphan1', 'no_job', 'no_account', '0', '1', 1.0)"
    )
    conn.commit()
    conn.close()
    report = db.check_integrity()
    assert report["quick_check"] == "ok"
    assert report["orphan_clips_no_job"] == 1
    assert report["orphan_clips_no_account"] == 1


def test_checkpoint_truncates_wal(db, tmp_path):
    db.create_account("acc_w", "W", "n", sources=[])
    # Force a checkpoint and confirm it reports no busy frames.
    busy, _log, _ckpt = db._conn().execute(
        "PRAGMA wal_checkpoint(TRUNCATE);"
    ).fetchone()
    assert busy == 0
    db.checkpoint(mode="TRUNCATE")  # helper path must not raise


# ---------------------------------------------------------------------------
# Legacy schema migration (pre-job_id clips)
# ---------------------------------------------------------------------------

_LEGACY_CLIPS_DDL = """
CREATE TABLE clips (
    id TEXT PRIMARY KEY,
    video_url TEXT,
    source_title TEXT,
    account_id TEXT,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration REAL NOT NULL,
    virality_score REAL DEFAULT 0.0,
    hook_summary TEXT,
    status TEXT,
    video_path TEXT,
    thumbnail_path TEXT,
    subtitles_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _make_legacy_db(tmp_path, user_version: int = 2) -> Path:
    """Build a dev-era DB that claims the current version but has the old
    clips shape — exactly what users' leftover storage/clipit.db files look
    like (accounts/jobs current, clips pre-job_id)."""
    import sqlite3 as _s
    p = tmp_path / "legacy.db"
    conn = _s.connect(str(p))
    template = """
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, niche TEXT NOT NULL,
            sources_json TEXT NOT NULL, branding_preset_json TEXT NOT NULL,
            metadata_preset_json TEXT NOT NULL, max_daily_clips INTEGER DEFAULT 3,
            enabled INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY, account_id TEXT NOT NULL, source_url TEXT NOT NULL,
            source_type TEXT NOT NULL, title TEXT, duration_seconds REAL,
            status TEXT NOT NULL DEFAULT 'PENDING', raw_video_path TEXT,
            audio_path TEXT, transcript_json TEXT, retry_count INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 3, error_log TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        {_LEGACY_CLIPS_DDL}
        INSERT INTO accounts (id, name, niche, sources_json, branding_preset_json,
            metadata_preset_json)
            VALUES ('acc_legacy', 'Legacy', 'n', '[]', '{{}}', '{{}}');
        INSERT INTO clips (id, video_url, source_title, account_id, start_time,
            end_time, duration, virality_score, hook_summary, status, video_path)
        VALUES ('legacy1', 'https://x/v', 'Legacy Title', 'acc_legacy', '0', '10',
            10.0, 0.9, 'hook summary', 'done', 'C:/legacy/out.mp4'),
               ('legacy2', 'https://x/v2', NULL, 'ghost_account', '1', '2', 1.0,
                0.1, NULL, 'done', NULL);
        PRAGMA user_version = {ver};
    """
    conn.executescript(template.format(_LEGACY_CLIPS_DDL=_LEGACY_CLIPS_DDL,
                                       ver=user_version))
    conn.close()
    return p


def test_legacy_clips_migrated_in_place(tmp_path):
    p = _make_legacy_db(tmp_path)
    db = Database(p)
    db.init_schema()
    assert db._conn().execute("PRAGMA user_version;").fetchone()[0] == SCHEMA_VERSION
    cols = {r[1] for r in db._conn().execute("PRAGMA table_info(clips);")}
    assert {"job_id", "caption_path", "approved", "hook_text",
            "duration_seconds"} <= cols
    # Compatible columns were carried over; the ghost-account row was dropped
    # (owner gone == ON DELETE CASCADE semantics), matching the warning log.
    rows = db.list_clips()
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "legacy1"
    assert r["title"] == "Legacy Title"
    assert r["hook_text"] == "hook summary"
    assert r["duration_seconds"] == 10.0
    assert r["video_path"] == "C:/legacy/out.mp4"
    assert r["account_id"] == "acc_legacy"
    assert r["job_id"] is None  # orphan-of-the-old-era, flagged by the scan
    db.close()


def test_migration_idempotent(tmp_path):
    p = _make_legacy_db(tmp_path)
    db = Database(p)
    db.init_schema()
    db.init_schema()  # second run must be a no-op
    rows = db.list_clips()
    assert len(rows) == 1  # only the owned legacy row survives
    assert {r[1] for r in db._conn().execute("PRAGMA table_info(clips);")} >= {
        "job_id", "caption_path"}
    db.close()


def test_migration_preserves_clip_indexes(tmp_path):
    p = _make_legacy_db(tmp_path)
    db = Database(p)
    db.init_schema()
    names = {r[0] for r in db._conn().execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
    assert {"idx_clips_job", "idx_jobs_status", "idx_jobs_account",
            "idx_oauth_account", "idx_oauth_provider"} <= names
    db.close()
