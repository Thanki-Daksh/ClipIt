"""
ClipIt System Healthcheck REST API (Agent 01)
--------------------------------------------
A small FastAPI app exposing ``GET /health`` with live metrics about:

  - database: schema version, WAL journal mode, foreign_keys on/off, db size
  - queue: job count per pipeline status, accounts enabled
  - storage: per-account isolated usage + overall disk free
  - runtime: uptime + timestamp

The health dependency is intentionally slim (raw sqlite + stdlib) so it can run
alongside the daemon without importing the heavy worker modules. Start with:

    python main.py serve --port 8001
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

from core.db import Database
from core.queue import PIPELINE, QueueEngine
from core.storage import AccountStorage

_STARTED_AT = time.time()


def _nice(n: float) -> str:
    """Human-readable byte size (e.g. 1.5M)."""
    if n < 1024:
        return f"{n:.0f}B"
    k = n / 1024
    if k < 1024:
        return f"{k:.1f}K"
    m = k / 1024
    if m < 1024:
        return f"{m:.1f}M"
    return f"{m / 1024:.2f}G"


def build_health_payload(db: Optional[Database] = None,
                         cfg=None,
                         storage_root: Optional[str | Path] = None) -> dict:
    """Assemble the /health response dict (never raises on missing db)."""
    payload: dict = {
        "status": "ok",
        "service": "clipit",
        "version": "1.0.0",
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        "timestamp": time.time(),
    }

    # ---------- database ----------
    db_info: dict = {"ok": False}
    if db is not None:
        try:
            conn = db._conn()
            db_info.update({
                "ok": True,
                "journal_mode": conn.execute("PRAGMA journal_mode;").fetchone()[0],
                "synchronous": conn.execute("PRAGMA synchronous;").fetchone()[0],
                "foreign_keys": conn.execute("PRAGMA foreign_keys;").fetchone()[0],
                "schema_version": conn.execute("PRAGMA user_version;").fetchone()[0],
                "size_bytes": db.db_path.stat().st_size if db.db_path.exists() else None,
            })
            # Live integrity probe: SQLite quick_check + orphaned-clip scan.
            integrity = db.check_integrity(quick=True)
            db_info.update(integrity)
        except Exception as exc:  # noqa: BLE001
            db_info["error"] = str(exc)
    payload["database"] = db_info

    # ---------- queue ----------
    queue_info: dict = {}
    if db is not None:
        try:
            engine = QueueEngine(db)
            counts: dict[str, int] = {}
            for row in db.list_jobs():
                counts[row["status"]] = counts.get(row["status"], 0) + 1
            for stage in PIPELINE:
                counts.setdefault(stage, 0)
            queue_info.update({
                "by_status": counts,
                "total_jobs": sum(counts.values()),
                "pending": counts.get("PENDING", 0),
                "accounts_enabled": len(db.list_accounts(enabled_only=True)),
            })
        except Exception as exc:  # noqa: BLE001
            queue_info["error"] = str(exc)
    payload["queue"] = queue_info

    # ---------- disk ----------
    try:
        disk = shutil.disk_usage(Path.cwd())
        payload["disk"] = {
            "free_bytes": disk.free,
            "total_bytes": disk.total,
            "free": _nice(disk.free),
            "total": _nice(disk.total),
            "used_percent": round(disk.used / disk.total * 100, 1),
        }
    except Exception as exc:  # noqa: BLE001
        payload["disk"] = {"error": str(exc)}

    # ---------- per-account storage isolation ----------
    if storage_root is not None:
        try:
            store = AccountStorage(storage_root)
            per_account = {
                acc_id: {"bytes": store.account_usage_bytes(acc_id),
                         "human": _nice(store.account_usage_bytes(acc_id))}
                for acc_id in store.list_accounts()
            }
            payload["storage"] = {"root": str(store.root), "per_account": per_account}
        except Exception as exc:  # noqa: BLE001
            payload["storage"] = {"error": str(exc)}

    return payload


def create_health_app(db: Optional[Database] = None,
                      storage_root: Optional[str | Path] = None):
    """Build a FastAPI app exposing GET /health."""
    from fastapi import FastAPI

    app = FastAPI(title="ClipIt Health API", version="1.0.0", docs_url=None)

    @app.get("/health")
    def health():
        return build_health_payload(db=db, storage_root=storage_root)

    return app


__all__ = ["build_health_payload", "create_health_app"]