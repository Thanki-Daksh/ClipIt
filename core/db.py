"""
ClipIt SQLite Database Core
---------------------------
Connection manager, schema migrations, and atomic transaction helpers.

Guarantees:
  - WAL journal mode for crash-safe concurrent reads/writes
  - `PRAGMA foreign_keys = ON` enforce referential integrity (cascade deletes)
  - `transaction()` context manager wraps every multi-statement state change
    in a single `BEGIN IMMEDIATE` transaction (atomicity / zero partial writes)
  - PRAGMA user_version tracks schema migrations

Usage:
    from core.db import Database
    db = Database("storage/clipit.db")
    db.init_schema()
    with db.transaction():
        db.create_job(...)
        db.transition_status(...)
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from core.logger import get_logger

log = get_logger("db")

SCHEMA_VERSION = 2

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    niche TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    branding_preset_json TEXT NOT NULL,
    metadata_preset_json TEXT NOT NULL,
    max_daily_clips INTEGER DEFAULT 3,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    title TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    raw_video_path TEXT,
    audio_path TEXT,
    transcript_json TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    -- job_id is nullable ONLY to admit legacy migrated rows that predate
    -- the job pipeline; the FK below still enforces referential integrity
    -- and every writer (create_clip) always supplies a real job.
    job_id TEXT,
    account_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    virality_score REAL DEFAULT 0.0,
    hook_text TEXT,
    video_path TEXT,
    caption_path TEXT,
    title TEXT,
    description TEXT,
    hashtags TEXT,
    approved INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    level TEXT NOT NULL,
    job_id TEXT,
    account_id TEXT,
    message TEXT NOT NULL,
    data_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_account ON jobs(account_id);
CREATE INDEX IF NOT EXISTS idx_clips_job ON clips(job_id);

-- OAuth / long-lived credential store (TSK-A01-10)
-- Stores YouTube Data API + Instagram Graph API tokens for N accounts
-- Token payloads are encrypted at rest via core/credentials (Fernet)
-- so raw columns hold only non-sensitive metadata like scopes & timestamps
CREATE TABLE IF NOT EXISTS oauth_credentials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    provider TEXT NOT NULL CHECK (provider IN ('youtube', 'instagram')),
    scopes TEXT,
    access_token_enc TEXT,
    refresh_token_enc TEXT,
    expires_at TIMESTAMP,
    revoked INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, provider),
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_oauth_account ON oauth_credentials(account_id);
CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_credentials(provider);
"""


# ---------------------------------------------------------------------------
# Connection wrapper
# ---------------------------------------------------------------------------

# COMMIT durability levels (PRAGMA synchronous). FULL fsyncs the WAL before
# COMMIT returns — the only level that guarantees zero data loss across an OS
# battery kill / power loss. NORMAL is crash-safe but can lose the last
# commits on power loss. OFF can even corrupt on power loss.
_SYNC_MODES: dict[str, int] = {"OFF": 0, "NORMAL": 1, "FULL": 2}
_SYNC_ENV = "CLIPIT_DB_SYNCHRONOUS"


def _resolve_sync_mode(override: Optional[str] = None) -> int:
    """Resolve the synchronous pragma value: explicit arg > env > FULL."""
    raw = (override or os.environ.get(_SYNC_ENV, "FULL")).strip().upper()
    if raw in ("0", "1", "2"):
        return int(raw)
    if raw in _SYNC_MODES:
        return _SYNC_MODES[raw]
    log.warning("invalid %s=%r; falling back to FULL (durable)", _SYNC_ENV, raw)
    return _SYNC_MODES["FULL"]


class Database:
    """Thread-safe SQLite connection manager with atomic transactions."""

    def __init__(self, db_path: str | Path, max_retries: int = 3,
                 synchronous: Optional[str] = None):
        self.db_path = Path(db_path)
        self.max_retries = max_retries
        # Durability: explicit arg > env > FULL (see _resolve_sync_mode).
        self._synchronous = _resolve_sync_mode(synchronous)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread (WAL allows concurrent readers + single writer)
        self._local = threading.local()
        self._write_lock = threading.Lock()
        log.debug("Database initialized at %s (synchronous=%s)",
                  self.db_path, self._synchronous)

    # -- connection management ---------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        journal = conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
        if journal != "wal":
            log.warning("journal_mode=%s (WAL unavailable on this filesystem); "
                        "durability degraded", journal)
        conn.execute(f"PRAGMA synchronous={self._synchronous};")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA busy_timeout=10000;")
        return conn

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._connect()
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ------------------------------------------------------------------
    # Schema / migrations
    # ------------------------------------------------------------------

    def init_schema(self) -> None:
        """Create all tables + indexes (idempotent; migrate if version older)."""
        with self.transaction() as conn:
            # Strip "--"-prefixed comment lines, then split on ";" so a comment
            # can never truncate a CREATE statement. executescript() would
            # auto-commit the enclosing tx, so run each statement individually.
            sql_lines = [
                ln for ln in _SCHEMA_SQL.splitlines()
                if not ln.lstrip().startswith("--")
            ]
            for stmt in "\n".join(sql_lines).split(";"):
                stmt_clean = stmt.strip()
                if stmt_clean:
                    try:
                        conn.execute(stmt_clean)
                    except sqlite3.OperationalError as exc:
                        if "already exists" not in str(exc):
                            log.debug("Schema stmt notice: %s", exc)
            current = conn.execute("PRAGMA user_version;").fetchone()[0]
            # user_version alone is not trustworthy: legacy dev DBs can claim the
            # current version while carrying an old clips shape. Detect drift by
            # inspecting columns so stale tables always get rebuilt.
            clip_cols = {r[1] for r in conn.execute("PRAGMA table_info(clips);")}
            if current < SCHEMA_VERSION or "job_id" not in clip_cols:
                self._migrate(conn, current, SCHEMA_VERSION)
                conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION};")
            log.info("schema initialized (user_version=%s)", SCHEMA_VERSION)

    @staticmethod
    def _migrate(conn: sqlite3.Connection, from_ver: int, to_ver: int) -> None:
        """
        Upgrade legacy databases to the current schema.

        The one wild migration: pre-job_id `clips` tables (old dev-era shape
        with video_url/source_title/duration/hook_summary/thumbnail_path/
        subtitles_json). Detection is by column rather than user_version
        because legacy files can carry an inflated version number.

        All work happens inside the caller's enclosing transaction, so a
        crash mid-migration rolls the whole upgrade back atomically.
        """
        clip_cols = {r[1] for r in conn.execute("PRAGMA table_info(clips);")}
        if clip_cols and "job_id" not in clip_cols:
            log.info("migrating legacy clips table -> current schema (v%s)", to_ver)
            conn.execute("ALTER TABLE clips RENAME TO clips_legacy;")

            # Re-run the current clips DDL (parsed from _SCHEMA_SQL) so the
            # live definition can never drift from the code. Comment lines
            # are stripped first (they can contain ';' and break the split).
            schema_sql = "\n".join(

                ln for ln in _SCHEMA_SQL.splitlines()
                if not ln.lstrip().startswith("--")
            )
            clips_ddl = next(
                stmt for stmt in schema_sql.split(";")
                if stmt.strip().startswith("CREATE TABLE IF NOT EXISTS clips ")
            ) + ";"
            conn.execute(clips_ddl)

            # Copy every compatible field; render-only legacy columns with no
            # modern equivalent (thumbnail/subtitles_json) are dropped and
            # regenerated by the pipeline. Rows whose owner account is gone
            # are dropped too - mirroring what the FK's ON DELETE CASCADE
            # would have done - and reported so nothing vanishes silently.
            # Surviving rows keep a NULL job_id (clips.job_id is nullable
            # exactly for this) and show up in check_integrity's orphan scan
            # until the operator purges or re-parents them.
            total_legacy = conn.execute(
                "SELECT COUNT(*) FROM clips_legacy"
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO clips (id, job_id, account_id, start_time, end_time, "
                "duration_seconds, virality_score, hook_text, title, video_path, "
                "caption_path, approved, created_at) "
                "SELECT id, NULL, account_id, start_time, end_time, duration, "
                "virality_score, hook_summary, source_title, video_path, NULL, 0, "
                "created_at FROM clips_legacy WHERE EXISTS ("
                "SELECT 1 FROM accounts a WHERE a.id = clips_legacy.account_id)"
            )
            migrated = conn.execute("SELECT COUNT(*) FROM clips").fetchone()[0]
            conn.execute("DROP TABLE clips_legacy;")
            dropped = total_legacy - migrated
            if dropped:
                log.warning(
                    "legacy clips migration dropped %s row(s) whose owner "
                    "account no longer exists (ON DELETE CASCADE semantics)",
                    dropped,
                )

            # The legacy rename can leave the clips index missing; recreate all
            # declared indexes (IF NOT EXISTS keeps this idempotent).
            for stmt in schema_sql.split(";"):
                if stmt.strip().startswith("CREATE INDEX"):
                    conn.execute(stmt + ";")
            log.info("legacy clips migrated: %s row(s) preserved (v%s)",
                     migrated, to_ver)

        log.debug("migration %s -> %s complete", from_ver, to_ver)

    # ------------------------------------------------------------------
    # Atomic transaction helper
    # ------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Atomic context manager. Wraps the body in BEGIN IMMEDIATE ... COMMIT.
        Anything raised rolls back the whole block.

        Guards against nested use: ``_write_lock`` is NOT reentrant, so a
        second transaction() on the same thread (e.g. ``log_event`` inside a
        write tx) would otherwise deadlock forever. We raise a clear error
        before even touching the lock.
        """
        conn = self._conn()
        if conn.in_transaction:
            raise RuntimeError(
                "nested transaction() on the same thread — the write lock is "
                "not reentrant. Move log_event()/nested writes outside the "
                "`with self.db.transaction()` block."
            )
        with self._write_lock:
            conn.execute("BEGIN IMMEDIATE;")
            try:
                yield conn
                conn.execute("COMMIT;")
            except BaseException:
                conn.execute("ROLLBACK;")
                raise

    # ------------------------------------------------------------------
    # Integrity + durability helpers
    # ------------------------------------------------------------------

    def check_integrity(self, quick: bool = True) -> dict:
        """
        PRAGMA integrity/quick_check plus a referential-integrity scan for
        orphaned clips (rows whose job/account no longer exists). Returns a
        dict; ``quick_check == "ok"`` and zero orphan counts mean healthy.
        """
        conn = self._conn()
        pragma = "quick_check" if quick else "integrity_check"
        result = conn.execute(f"PRAGMA {pragma};").fetchone()[0]
        orphans_no_job = conn.execute(
            "SELECT COUNT(*) FROM clips c LEFT JOIN jobs j ON j.id = c.job_id "
            "WHERE j.id IS NULL"
        ).fetchone()[0]
        orphans_no_account = conn.execute(
            "SELECT COUNT(*) FROM clips c LEFT JOIN accounts a ON a.id = c.account_id "
            "WHERE a.id IS NULL"
        ).fetchone()[0]
        return {
            "check": pragma,
            "quick_check": result,
            "orphan_clips_no_job": orphans_no_job,
            "orphan_clips_no_account": orphans_no_account,
        }

    def checkpoint(self, mode: str = "TRUNCATE") -> None:
        """
        Run ``PRAGMA wal_checkpoint(<mode>)`` on this thread's connection so
        the WAL is folded back into the main DB file. Call on graceful daemon
        shutdown to keep sidecars small after a long run.
        """
        conn = self._conn()
        busy, log_frames, checkpointed = conn.execute(
            f"PRAGMA wal_checkpoint({mode});"
        ).fetchone()
        log.info("wal checkpoint %s: busy=%s log=%s frames=%s",
                 mode, busy, log_frames, checkpointed)

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_event(self, level: str, message: str, job_id: Optional[str] = None,
                  account_id: Optional[str] = None, data: Optional[dict] = None) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO logs (level, job_id, account_id, message, data_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (level, job_id, account_id, message,
                 json.dumps(data, default=str) if data else None),
            )

    # Convenience alias kept for backward compatibility with older call sites.
    log = log_event

    # ------------------------------------------------------------------
    # Accounts CRUD
    # ------------------------------------------------------------------

    def create_account(self, account_id: str, name: str, niche: str,
                       sources: list[str],
                       branding_preset: Optional[dict] = None,
                       metadata_preset: Optional[dict] = None,
                       max_daily_clips: int = 3, enabled: int = 1) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO accounts (id, name, niche, sources_json, branding_preset_json, "
                "metadata_preset_json, max_daily_clips, enabled) VALUES (?,?,?,?,?,?,?,?)",
                (account_id, name, niche,
                 json.dumps(sources),
                 json.dumps(branding_preset or {}),
                 json.dumps(metadata_preset or {}),
                 max_daily_clips, enabled),
            )
        log.info("account created: %s (%s)", account_id, name)

    def get_account(self, account_id: str) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        ).fetchone()

    def list_accounts(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        if enabled_only:
            return self._conn().execute(
                "SELECT * FROM accounts WHERE enabled = 1 ORDER BY name"
            ).fetchall()
        return self._conn().execute("SELECT * FROM accounts ORDER BY name").fetchall()

    def delete_account(self, account_id: str) -> bool:
        """Delete an account and cascade to its jobs/clips/credentials."""
        with self.transaction() as conn:
            cur = conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        if cur.rowcount:
            log.info("deleted account %s (cascaded dependent rows)", account_id)
        return cur.rowcount > 0

    def account_sources(self, account_id: str) -> list[str]:
        row = self.get_account(account_id)
        if row is None:
            return []
        try:
            return json.loads(row["sources_json"])
        except (TypeError, json.JSONDecodeError):
            return []

    # ------------------------------------------------------------------
    # Jobs CRUD / state
    # ------------------------------------------------------------------

    def create_job(self, account_id: str, source_url: str, source_type: str,
                   title: Optional[str] = None,
                   max_retries: Optional[int] = None,
                   status: str = "PENDING") -> str:
        job_id = uuid.uuid4().hex[:16]
        if max_retries is None:
            max_retries = self.max_retries
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO jobs (id, account_id, source_url, source_type, title, "
                "status, max_retries) VALUES (?,?,?,?,?,?,?)",
                (job_id, account_id, source_url, source_type, title, status, max_retries),
            )
        log.info("job enqueued: %s [%s] -> %s", job_id, source_type, account_id)
        return job_id

    def get_job(self, job_id: str) -> Optional[sqlite3.Row]:
        return self._conn().execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()

    def list_jobs(self, status: Optional[str] = None,
                  account_id: Optional[str] = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM jobs"
        clauses, args = [], []
        if status:
            clauses.append("status = ?")
            args.append(status)
        if account_id:
            clauses.append("account_id = ?")
            args.append(account_id)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY created_at DESC"
        return self._conn().execute(sql, args).fetchall()

    def _set_status(self, conn: sqlite3.Connection, job_id: str, status: str,
                    **fields: Any) -> None:
        cols, args = [], []
        for key, val in fields.items():
            if val is not None:
                cols.append(f"{key} = ?")
                args.append(val)
        args.append(status)
        cols.append("status = ?")
        args.append(job_id)
        conn.execute(f"UPDATE jobs SET {', '.join(cols)}, updated_at=CURRENT_TIMESTAMP "
                     "WHERE id = ?", args)

    def update_job_status(self, job_id: str, status: str, **fields: Any) -> None:
        """Atomic single-status update of an in-flight job."""
        with self.transaction() as conn:
            self._set_status(conn, job_id, status, **fields)

    # ------------------------------------------------------------------
    # Clips CRUD
    # ------------------------------------------------------------------

    def create_clip(self, job_id: str, account_id: str, start_time: str,
                    end_time: str, duration_seconds: float,
                    virality_score: float = 0.0, hook_text: Optional[str] = None,
                    title: Optional[str] = None, description: Optional[str] = None,
                    hashtags: Optional[str] = None,
                    video_path: Optional[str] = None,
                    caption_path: Optional[str] = None) -> str:
        clip_id = uuid.uuid4().hex[:16]
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO clips (id, job_id, account_id, start_time, end_time, "
                "duration_seconds, virality_score, hook_text, title, description, "
                "hashtags, video_path, caption_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (clip_id, job_id, account_id, start_time, end_time, duration_seconds,
                 virality_score, hook_text, title, description, hashtags,
                 video_path, caption_path),
            )
        return clip_id

    def list_clips(self, job_id: Optional[str] = None) -> list[sqlite3.Row]:
        if job_id:
            return self._conn().execute(
                "SELECT * FROM clips WHERE job_id = ? ORDER BY virality_score DESC", (job_id,)
            ).fetchall()
        return self._conn().execute("SELECT * FROM clips ORDER BY created_at DESC").fetchall()

    def update_clip(self, clip_id: str, **fields: Any) -> None:
        """Atomically update render/result columns on an existing clip."""
        if not fields:
            return
        allowed = {"video_path", "caption_path", "title", "description",
                   "hashtags", "approved", "virality_score", "metadata"}
        sets = ", ".join(f"{k}=?" for k in fields if k in allowed)
        args = [fields[k] for k in fields if k in allowed]
        if not sets:
            return
        args.append(clip_id)
        with self.transaction() as conn:
            conn.execute(f"UPDATE clips SET {sets} WHERE id=?", args)

    # ------------------------------------------------------------------
    # Daily clip budget (for the N-account scheduler)
    # ------------------------------------------------------------------

    def clips_created_today(self, account_id: str) -> int:
        """Count generated clips for an account created since local midnight."""
        midnight = datetime.now().strftime("%Y-%m-%d 00:00:00")
        row = self._conn().execute(
            "SELECT COUNT(*) AS n FROM clips WHERE account_id = ? AND created_at >= ?",
            (account_id, midnight),
        ).fetchone()
        return int(row["n"])

    def pending_jobs_for_account(self, account_id: str) -> list[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM jobs WHERE account_id = ? AND status = 'PENDING' "
            "ORDER BY created_at ASC", (account_id,)
        ).fetchall()


# ------------------------------------------------------------------
    # OAuth credentials (TSK-A01-10) — YouTube Data API / Instagram Graph API
    # ------------------------------------------------------------------

    def upsert_oauth_credential(
        self,
        account_id: str,
        provider: str,
        access_token_enc: Optional[str] = None,
        refresh_token_enc: Optional[str] = None,
        scopes: Optional[str] = None,
        expires_at: Optional[str] = None,
    ) -> None:
        """
        Insert or update a single OAuth credential row for an account+provider.
        Token payloads are expected to already be encrypted by the caller
        (core/credentials); this layer only persists ciphertext.
        """
        if provider not in ("youtube", "instagram"):
            raise ValueError(f"unsupported credential provider: {provider}")
        if not self.get_account(account_id):
            raise ValueError(f"unknown account: {account_id}")

        with self.transaction() as conn:
            existing = conn.execute(
                "SELECT id FROM oauth_credentials WHERE account_id=? AND provider=?",
                (account_id, provider),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE oauth_credentials SET access_token_enc=?, refresh_token_enc=?, "
                    "scopes=?, expires_at=?, revoked=0, updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=?",
                    (access_token_enc, refresh_token_enc, scopes, expires_at, existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO oauth_credentials "
                    "(account_id, provider, access_token_enc, refresh_token_enc, scopes, expires_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (account_id, provider, access_token_enc, refresh_token_enc, scopes, expires_at),
                )
        log.info("oauth credential upserted: %s/%s", account_id, provider)

    def get_oauth_credential(self, account_id: str, provider: str) -> Optional[sqlite3.Row]:
        return self._conn().execute(
            "SELECT * FROM oauth_credentials WHERE account_id=? AND provider=? AND revoked=0",
            (account_id, provider),
        ).fetchone()

    def list_oauth_credentials(self, provider: Optional[str] = None) -> list[sqlite3.Row]:
        if provider:
            return self._conn().execute(
                "SELECT * FROM oauth_credentials WHERE provider=? ORDER BY updated_at DESC",
                (provider,),
            ).fetchall()
        return self._conn().execute(
            "SELECT * FROM oauth_credentials ORDER BY updated_at DESC"
        ).fetchall()

    def revoke_oauth_credential(self, account_id: str, provider: str) -> bool:
        """Soft-revoke a credential (keeps the row for audit, flags revoked=1)."""
        with self.transaction() as conn:
            cur = conn.execute(
                "UPDATE oauth_credentials SET revoked=1, updated_at=CURRENT_TIMESTAMP "
                "WHERE account_id=? AND provider=?",
                (account_id, provider),
            )
        return cur.rowcount > 0

    def delete_oauth_credential(self, account_id: str, provider: str) -> bool:
        with self.transaction() as conn:
            cur = conn.execute(
                "DELETE FROM oauth_credentials WHERE account_id=? AND provider=?",
                (account_id, provider),
            )
        return cur.rowcount > 0


def datetime_utc() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


__all__ = ["Database", "SCHEMA_VERSION"]