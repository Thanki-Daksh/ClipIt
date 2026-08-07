"""
ClipIt Centralized Logging System
---------------------------------
Structured JSON (file) + human-readable (console) logging.

Usage:
    from core.logger import setup_logging, get_logger
    setup_logging(level="INFO", log_dir="storage/logs")
    log = get_logger("db")
    log.info("job created", extra={"fields": {"job_id": job_id}})
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_CONSOLE_DATE_FORMAT = "%H:%M:%S"

_configured: bool = False


class JsonFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects (for file sink)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Optional structured fields injected via extra={"fields": {...}}
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload["fields"] = fields
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def _parse_level(level: str) -> int:
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def setup_logging(
    level: str = "INFO",
    log_dir: Optional[str | Path] = None,
    json_file: bool = True,
    console: bool = True,
) -> None:
    """
    Configure root ClipIt logger. Safe to call multiple times (idempotent).

    Args:
        level: DEBUG / INFO / WARNING / ERROR / CRITICAL
        log_dir: directory for clipit.log (JSON lines). Defaults to
                 <project_root>/storage/logs.
        json_file: write structured JSON log file.
        console: write human-readable output to stdout.
    """
    global _configured
    root = logging.getLogger()
    root.setLevel(_parse_level(level))

    if _configured:
        return  # keep existing handlers; do not duplicate sinks

    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter(_CONSOLE_FORMAT, datefmt=_CONSOLE_DATE_FORMAT)
        )
        root.addHandler(console_handler)

    if json_file:
        log_dir = Path(log_dir) if log_dir else _default_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "clipit.log", encoding="utf-8")
        file_handler.setFormatter(JsonFormatter())
        root.addHandler(file_handler)

    # Keep the noise floor low: libraries should not spam our console.
    for noisy in ("urllib3", "requests", "yt_dlp", "httpcore", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def _default_log_dir() -> Path:
    """storage/logs relative to the project root (two levels up from core/)."""
    core_dir = Path(__file__).resolve().parent
    return core_dir.parent / "storage" / "logs"


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, e.g. get_logger('queue') -> 'core.queue'."""
    if not _configured:
        setup_logging()
    return logging.getLogger(f"core.{name}")


__all__ = ["setup_logging", "get_logger", "JsonFormatter"]
