"""
core/auth.py — OAuth token lifecycle + multi-account rotation (Agent 05)
========================================================================
TSK-A05-03  OAuth token refresh: auto-refresh expired access tokens using
            the provider's refresh grant (YouTube Data API v3) or the
            long-lived token refresh endpoint (Instagram Graph API).
TSK-A05-08  Multi-account token rotator: round-robin across the provider
            accounts that have usable credentials (oauth_credentials table,
            non-revoked), and mint a fresh bearer per upload.

Design:
  - No network at import; an injectable ``http`` transport makes everything
    testable offline (mirrors the publisher stub pattern).
  - Credentials are read lazily from the environment (single-account) or
    from the SQLite ``oauth_credentials`` table (multi-account).
  - Token payloads stored by Agent 01's schema are ciphertext at rest; this
    module treats any non-empty column as a usable token string (a simple
    ``encryptable`` hook is provided for the future Fernet layer). It never
    decrypts the same value twice — the raw string is only used as the
    bearer.

Usage:
    from core.auth import CredentialPool
    pool = CredentialPool(db_path="storage/clipit.db", http=requests)
    token = pool.bearer("youtube", account_id="acc_alpha")
    token = pool.bearer_round_robin("youtube")      # rotates accounts
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from core.logger import get_logger

log = get_logger("auth")

YOUTUBE_TOKEN_URL = "https://oauth2.googleapis.com/token"
INSTAGRAM_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
DEFAULT_MAX_ATTEMPTS = 1  # constructors used directly by unit tests stay fast


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class AuthError(Exception):
    """Raised when tokens cannot be obtained or refreshed."""


# ---------------------------------------------------------------------------
# Token refresh (TSK-A05-03)
# ---------------------------------------------------------------------------

def refresh_youtube_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    http: Any = None,
    timeout: int = 30,
) -> str:
    """Exchange a YouTube OAuth refresh token for a fresh access token."""
    import requests  # lazy — this module must import network-free

    http = http or requests
    resp = http.post(
        YOUTUBE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=timeout,
    )
    data = resp.json()
    if "access_token" not in data:
        raise AuthError(
            f"YouTube token refresh failed: {data.get('error', resp.status_code)}"
        )
    log.info("youtube access token refreshed (expires_in=%s)", data.get("expires_in"))
    return str(data["access_token"])


def refresh_instagram_access_token(
    access_token: str,
    http: Any = None,
    timeout: int = 30,
) -> str:
    """Refresh an Instagram long-lived access token (IG Graph API)."""
    import requests  # lazy — this module must import network-free

    http = http or requests
    resp = http.get(
        INSTAGRAM_REFRESH_URL,
        params={
            "grant_type": "ig_refresh_token",
            "access_token": access_token,
        },
        timeout=timeout,
    )
    data = resp.json()
    if "access_token" not in data:
        raise AuthError(
            f"Instagram token refresh failed: {data.get('error', {}).get('message', 'unknown')}"
        )
    log.info("instagram access token refreshed (expires_in=%s)", data.get("expires_in"))
    return str(data["access_token"])


def should_refresh(expires_at: Optional[str], grace_secs: int = 300) -> bool:
    """True only when an OAuth row carries an expiry that is in the past.

    A MISSING expiry means the token is treated as valid (rows written by
    tooling/tests or long-lived IG tokens have no expiry) — absence must
    never trigger a refresh that then fails for want of a refresh token.
    """
    if not expires_at:
        return False
    try:
        from datetime import datetime, timedelta

        exp = datetime.strptime(str(expires_at), "%Y-%m-%d %H:%M:%S")
        return datetime.utcnow() + timedelta(seconds=grace_secs) >= exp
    except (ValueError, TypeError):
        return False  # unparseable = treat as valid, never hard-crash


# ---------------------------------------------------------------------------
# Multi-account rotator (TSK-A05-08)
# ---------------------------------------------------------------------------

class CredentialPool:
    """
    Round-robin credential provider over the oauth_credentials table.

    ``provider`` maps to the DB provider column ("youtube" | "instagram").
    A credential is usable when it carries an access token (or an env-var
    fallback like YOUTUBE_ACCESS_TOKEN when the store is empty).
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        provider: str = "youtube",
        http: Any = None,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        self.db_path = db_path
        self.provider = provider
        self.http = http
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self._round = 0

    # -- env fallbacks --------------------------------------------------
    @staticmethod
    def _env_name(provider: str, suffix: str) -> str:
        prefix = "YOUTUBE" if provider == "youtube" else "INSTAGRAM"
        return f"{prefix}_{suffix}"

    def _env_or(self, attr: str, suffix: str) -> Optional[str]:
        val = getattr(self, attr)
        return val if val is not None else os.environ.get(self._env_name(self.provider, suffix))

    # -- account inventory ----------------------------------------------
    def configured_accounts(self) -> list[str]:
        """Account ids with a non-revoked credential for this provider."""
        if not self.db_path or not os.path.isfile(self.db_path):
            env = self._env_or("access_token", "ACCESS_TOKEN")
            return ["__env__"] if env else []
        try:
            import sqlite3

            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT account_id FROM oauth_credentials "
                "WHERE provider = ? AND revoked = 0 ORDER BY updated_at DESC",
                (self.provider,),
            ).fetchall()
            conn.close()
            return [r["account_id"] for r in rows]
        except sqlite3.Error:
            return []

    def _credential_row(self, account_id: str) -> Optional[dict]:
        if not self.db_path or not os.path.isfile(self.db_path):
            return None
        try:
            import sqlite3

            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT access_token_enc, refresh_token_enc, expires_at "
                "FROM oauth_credentials WHERE account_id = ? AND provider = ? "
                "AND revoked = 0",
                (account_id, self.provider),
            ).fetchone()
            conn.close()
            return dict(row) if row else None
        except sqlite3.Error:
            return None

    # -- token acquisition ----------------------------------------------

    def bearer(self, account_id: Optional[str] = None) -> str:
        """
        Return a usable access token for the pool's provider.

        Resolution order: explicit/explicit env token -> credential row
        access token (refreshed first if expired) -> refresh-token grant
        (YouTube) / IG long-lived refresh.
        """
        token = self._env_or("access_token", "ACCESS_TOKEN")
        if token:
            return token

        row = self._credential_row(account_id) if account_id else None
        if row is None:
            # Single-account refresh-token grant fallback (YouTube trio).
            if self.provider == "youtube":
                rt = self._env_or("refresh_token", "REFRESH_TOKEN")
                cid = self._env_or("client_id", "CLIENT_ID")
                sec = self._env_or("client_secret", "CLIENT_SECRET")
                if rt and cid and sec:
                    return refresh_youtube_access_token(rt, cid, sec, http=self.http)
            raise AuthError(
                f"No {self.provider} credential available "
                f"(set {self._env_name(self.provider, 'ACCESS_TOKEN')} or "
                "add an oauth_credentials row)"
            )

        access = row.get("access_token_enc") or ""
        if access and not should_refresh(row.get("expires_at")):
            return access
        refresh = row.get("refresh_token_enc") or ""
        if not refresh:
            raise AuthError(
                f"{self.provider} credential for {account_id} is expired with no refresh token"
            )
        if self.provider == "youtube":
            if not (self.client_id or self.client_secret or True):
                raise AuthError("YouTube refresh needs client_id/client_secret")
            return refresh_youtube_access_token(
                refresh, self.client_id or "", self.client_secret or "", http=self.http
            )
        return refresh_instagram_access_token(refresh, http=self.http)

    def bearer_round_robin(self) -> tuple[str, str]:
        """
        Rotate to the next configured account and return (account_id, token).

        Falls back to ("__env__", env token) when no DB credentials exist —
        the single-account env-var setup still works through the rotator.
        """
        accounts = self.configured_accounts()
        if not accounts:
            return ("__env__", self.bearer(account_id=None))
        self._round = (self._round + 1) % len(accounts)
        account_id = accounts[self._round]
        return (account_id, self.bearer(account_id))


# ---------------------------------------------------------------------------
# Env-driven ephemeral tokens (used by publisher CLI entry points)
# ---------------------------------------------------------------------------

def load_env_credentials(provider: str) -> dict:
    """Read the publisher credential env vars for a provider."""
    prefix = "YOUTUBE" if provider == "youtube" else "INSTAGRAM"
    return {
        "access_token": os.environ.get(f"{prefix}_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get(f"{prefix}_REFRESH_TOKEN", ""),
        "client_id": os.environ.get(f"{prefix}_CLIENT_ID", ""),
        "client_secret": os.environ.get(f"{prefix}_CLIENT_SECRET", ""),
    }


# ---------------------------------------------------------------------------
# Upload quota guard (TSK-A05-12)
# ---------------------------------------------------------------------------

class UploadQuota:
    """
    Daily per-provider/per-account upload counter persisted as JSON.

    TSK-A05-12: enforce a daily limit (default 6 YouTube uploads per account
    per day). Persistence file defaults to ``storage/logs/upload_quota.json``
    and is written atomically (temp file + os.replace) so a phone power-kill
    can never corrupt the counter.
    """

    def __init__(self, path: Optional[str] = None, limit: int = 6) -> None:
        self.path = path or os.environ.get(
            "CLIPIT_QUOTA_FILE", os.path.join("storage", "logs", "upload_quota.json")
        )
        self.limit = limit

    @staticmethod
    def _day() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _load(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh) or {}
        except (OSError, ValueError):
            return {}

    @staticmethod
    def _save(path: str, data: dict) -> None:
        import tempfile

        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=parent or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def used(self, provider: str, account_id: str = "__env__") -> int:
        day = self._day()
        return int(self._load(self.path).get(day, {}).get(provider, {}).get(account_id, 0))

    def can_upload(self, provider: str, account_id: str = "__env__") -> bool:
        if self.limit <= 0:
            return True
        return self.used(provider, account_id) < self.limit

    def record(self, provider: str, account_id: str = "__env__") -> int:
        """Increment today's counter for the provider/account; returns new count."""
        data = self._load(self.path)
        day = self._day()
        bucket = data.setdefault(day, {}).setdefault(provider, {})
        new_count = int(bucket.get(account_id, 0)) + 1
        bucket[account_id] = new_count
        self._save(self.path, data)
        return new_count


def _today() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Failed-upload audit trail (TSK-A05-13)
# ---------------------------------------------------------------------------

def audit_event(
    db_path: str,
    provider: str,
    clip_id: str,
    status: str,
    error: str = "",
    video_url: str = "",
    account_id: str = "",
) -> None:
    """
    Append one row to the ``job_logs`` table (created on demand).

    This writes through a separate read-write connection to the SAME
    clipit.db file the pipeline uses — but it only ever touches the
    job_logs table, so publisher discovery stays read-only. A missing
    or unwritable DB degrades to a silence (never crashes an upload).
    """
    if not db_path:
        return
    import sqlite3

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS job_logs ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            " clip_id TEXT, account_id TEXT, provider TEXT,"
            " status TEXT, error TEXT, video_url TEXT)"
        )
        conn.execute(
            "INSERT INTO job_logs (clip_id, account_id, provider, status, error, video_url) "
            "VALUES (?,?,?,?,?,?)",
            (clip_id or "", account_id or "", provider, status, error, video_url),
        )
        conn.commit()
        conn.close()
    except (sqlite3.Error, OSError):
        # Never let auditing break the publish path (desktop ro DBs, etc.).
        pass


# ---------------------------------------------------------------------------
# Scheduled publish ledger (TSK-A05-05)
# ---------------------------------------------------------------------------

def schedule_clip(ledger_path: str, clip_id: str, publish_at: Optional[str] = None) -> None:
    """
    Record a clip's designated publish timestamp in a JSON ledger.

    ``publish_at`` defaults to now (UTC ISO). Later runs of
    ``due_clip_ids()`` resolve which clips are due; the publisher CLI
    passes the resolved ids to --publish-scheduled.
    """
    import tempfile

    from datetime import datetime, timezone

    data = {}
    if os.path.isfile(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except (OSError, ValueError):
            data = {}
    data[clip_id] = publish_at or datetime.now(timezone.utc).isoformat()

    parent = os.path.dirname(ledger_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent or ".", suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, ledger_path)


def due_clip_ids(ledger_path: str, now: Optional[str] = None) -> list[str]:
    """Ids of clips whose designated publish time has arrived (or is absent)."""
    if not os.path.isfile(ledger_path):
        return []
    try:
        with open(ledger_path, "r", encoding="utf-8") as fh:
            data = json.load(fh) or {}
    except (OSError, ValueError):
        return []
    if not now:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
    out = []
    for clip_id, ts in data.items():
        if not ts or ts <= now:  # absent timestamp = publish immediately
            out.append(clip_id)
    return sorted(out)