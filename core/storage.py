"""
ClipIt Account Storage Isolation
--------------------------------
Enforces per-account directory segregation so raw videos, extracted audio,
and rendered clips never collide across accounts. All paths resolve against a
root and are guarded against path traversal (`..` escapes).

Per-account layout (written under ``storage_root``):
    {account_id}/raw/       -> downloaded source video (raw_video_path)
    {account_id}/audio/     -> extracted 16kHz WAV (audio_path)
    {account_id}/clips/     -> final rendered 9:16 MP4 clips
    {account_id}/ass/       -> ASS caption files
    {account_id}/outputs/   -> metadata.json + export package

Usage:
    from core.storage import AccountStorage
    store = AccountStorage(BASE_DIR / "storage" / "accounts")
    layout = store.layout("acc_a")          # creates all dirs, returns paths
    store.sync_job_paths(job, "acc_a")      # set raw/audio paths on a job
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger("storage")

_SUBDIRS = ("raw", "audio", "clips", "ass", "outputs")


class StorageError(Exception):
    """Invalid or unsafe storage path."""


class AccountStorage:
    """Resolves and enforces isolated per-account storage under a single root."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # -- path resolution ---------------------------------------------------

    def _account_path(self, account_id: str) -> Path:
        if not account_id or "/" in account_id or "\\" in account_id or ".." in account_id:
            raise StorageError(f"unsafe account id: {account_id!r}")
        p = (self.root / account_id).resolve()
        if not str(p).startswith(str(self.root)):
            raise StorageError(f"account path escapes storage root: {account_id!r}")
        p.mkdir(parents=True, exist_ok=True)
        return p

    def _subdir(self, account_id: str, sub: str) -> Path:
        if sub not in _SUBDIRS:
            raise StorageError(f"unknown subdir {sub!r}")
        d = self._account_path(account_id) / sub
        d.mkdir(parents=True, exist_ok=True)
        return d

    # -- accessors -----------------------------------------------------------

    def account_dir(self, account_id: str) -> Path:
        return self._account_path(account_id)

    def raw_dir(self, account_id: str) -> Path:
        return self._subdir(account_id, "raw")

    def audio_dir(self, account_id: str) -> Path:
        return self._subdir(account_id, "audio")

    def clips_dir(self, account_id: str) -> Path:
        return self._subdir(account_id, "clips")

    def ass_dir(self, account_id: str) -> Path:
        return self._subdir(account_id, "ass")

    def outputs_dir(self, account_id: str) -> Path:
        return self._subdir(account_id, "outputs")

    def layout(self, account_id: str) -> dict[str, Path]:
        """Create (idempotently) and return the full per-account layout."""
        return {
            "account": self.account_dir(account_id),
            "raw": self.raw_dir(account_id),
            "audio": self.audio_dir(account_id),
            "clips": self.clips_dir(account_id),
            "ass": self.ass_dir(account_id),
            "outputs": self.outputs_dir(account_id),
        }

    # -- helpers ---------------------------------------------------------

    def raw_path(self, account_id: str, filename: str) -> Path:
        return self.raw_dir(account_id) / filename

    def audio_path(self, account_id: str, filename: str) -> Path:
        return self.audio_dir(account_id) / filename

    def clip_path(self, account_id: str, clip_id: str) -> Path:
        return self.clips_dir(account_id) / f"{clip_id}.mp4"

    def ass_path(self, account_id: str, clip_id: str) -> Path:
        return self.ass_dir(account_id) / f"{clip_id}.ass"

    def account_usage_bytes(self, account_id: str) -> int:
        """Total bytes on disk for an account's isolated tree (0 if none)."""
        acc = self.account_dir(account_id)
        return sum(f.stat().st_size for f in acc.rglob("*") if f.is_file())

    def list_accounts(self) -> list[str]:
        """Account ids that have an on-disk directory."""
        if not self.root.exists():
            return []
        return [d.name for d in self.root.iterdir() if d.is_dir()]

    def wipe_account(self, account_id: str) -> bool:
        """Remove an account's storage tree (idempotent). Returns True if removed.
        Does NOT re-create the directory; an absent dir returns False."""
        if not account_id or "/" in account_id or "\\" in account_id or ".." in account_id:
            raise StorageError(f"unsafe account id: {account_id!r}")
        acc = (self.root / account_id).resolve()
        if not str(acc).startswith(str(self.root)):
            raise StorageError(f"account path escapes storage root: {account_id!r}")
        if acc.exists():
            shutil.rmtree(acc)
            log.info("wiped storage for account %s", account_id)
            return True
        return False


__all__ = ["AccountStorage", "StorageError"]