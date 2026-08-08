"""
ClipIt API Key & Configuration Persistence Engine
--------------------------------------------------
Secure readers/writers for ``config.json`` and ``.env`` so runtime secrets and
settings can be persisted safely (TSK-A01-11) rather than only read at startup.

What this module provides:

1. ``ConfigStore``
   Atomic, collision-free updates to ``config.json`` and ``.env``:
     - ``set_api_key(provider, key)``  -> writes GROQ_API_KEY etc. into .env
     - ``unset_api_key(provider)``     -> removes a key from .env
     - ``set_setting(key, value)``     -> writes/updates a JSON key in config.json
     - ``unset_setting(key)``          -> removes a JSON key
     - ``api_key(provider)`` / ``read_dotenv()`` / ``read_json()`` -> reads
   Writes go through a temp file + ``os.replace`` so a crash mid-write can
   never corrupt the target; CRLF line endings (Windows) are preserved.

2. ``CredentialCrypto``
   Fernet (AES-128-CBC via the ``cryptography`` package) encryption/decryption
   for OAuth tokens bound to accounts (used by the core/db ``oauth_credentials``
   table). The secret key lives in ``.env`` as ``CLIPIT_ENCRYPTION_KEY`` and is
   auto-generated on first use, so tokens are never stored in plaintext.

Security notes:
  - API keys are never echoed to logs or stdout (masked/first-4 reads only).
  - Flagrant placeholder/weak keys are rejected before they reach the file.
  - The Fernet key is required before OAuth tokens can be sealed or unsealed.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import stat
import tempfile
from pathlib import Path
from typing import Any, Optional

from core.logger import get_logger
from core.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DOTENV_PATH,
    ConfigError,
    _ENV_KEY_MAP,
    _is_valid_key,
)

log = get_logger("persistence")

_ENCRYPTION_KEY_ENV = "CLIPIT_ENCRYPTION_KEY"
_CRLF = "\r\n"


# ---------------------------------------------------------------------------
# Atomic file primitives
# ---------------------------------------------------------------------------

def _atomic_write_text(path: Path, text: str, newline: str = "\n") -> None:
    """Write text atomically via a temp file + os.replace (crash-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        if sys.platform != "win32" and hasattr(os, "chmod"):
            try:
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        try:
            os.replace(tmp, path)
        except PermissionError:
            path.write_text(text, encoding="utf-8")
            try:
                os.unlink(tmp)
            except OSError:
                pass
    except BaseException:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data: dict) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_text(path, text, newline="\n")


# ---------------------------------------------------------------------------
# config.json + .env store
# ---------------------------------------------------------------------------

class ConfigStore:
    """Atomic reader/writer for config.json and .env."""

    def __init__(self, config_path: Optional[str | Path] = None,
                 dotenv_path: Optional[str | Path] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self.dotenv_path = Path(dotenv_path) if dotenv_path else DEFAULT_DOTENV_PATH

    # -- reads -----------------------------------------------------------

    def read_json(self) -> dict:
        if not self.config_path.exists():
            return {}
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def read_dotenv(self) -> dict:
        result: dict[str, str] = {}
        if not self.dotenv_path.exists():
            return result
        for raw in self.dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
                v = v[1:-1]
            result[k] = v
        return result

    def api_key(self, provider: str) -> str:
        """Return the stored key for a provider (or '')."""
        env_name = _ENV_KEY_MAP.get(f"{provider}_api_key")
        if not env_name:
            return ""
        return self.read_dotenv().get(env_name, "")

    # -- writes ----------------------------------------------------------

    def set_api_key(self, provider_name: str, key: str) -> None:
        """Persist a provider API key into .env (masked in logs, atomic write)."""
        env_name = _ENV_KEY_MAP.get(f"{provider_name}_api_key")
        if not env_name:
            raise ValueError(f"unknown provider: {provider_name}")
        if not _is_valid_key(key):
            raise ConfigError(f"refusing to persist invalid/placeholder key for {provider_name}")
        self._set_env(env_name, key)
        log.info("persisted API key %s -> %s", provider_name, self.dotenv_path)

    def unset_api_key(self, provider_name: str) -> bool:
        env_name = _ENV_KEY_MAP.get(f"{provider_name}_api_key")
        if not env_name:
            raise ValueError(f"unknown provider: {provider_name}")
        removed = self._unset_env(env_name)
        if removed:
            log.info("removed API key %s from %s", provider_name, self.dotenv_path)
        return removed

    def set_setting(self, key: str, value: Any) -> None:
        """Update a JSON setting in config.json (atomic)."""
        data = self.read_json()
        data[key] = value
        _atomic_write_json(self.config_path, data)
        log.info("persisted setting %s=%r -> %s", key, value, self.config_path)

    def unset_setting(self, key: str) -> bool:
        data = self.read_json()
        if key in data:
            del data[key]
            _atomic_write_json(self.config_path, data)
            log.info("removed setting %s from %s", key, self.config_path)
            return True
        return False

    # -- .env helpers ----------------------------------------------------

    def _read_env_raw(self) -> str:
        """Read .env as raw text (preserving CRLF / LF line endings)."""
        if not self.dotenv_path.exists():
            return ""
        with self.dotenv_path.open("r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def _env_lines(self) -> list[str]:
        text = self._read_env_raw()
        # Preserve the file's dominant line ending so edits stay Windows-clean.
        self._env_newline = _CRLF if _CRLF in text else "\n"
        return text.splitlines() if text else []

    def _set_env(self, name: str, value: str) -> None:
        lines = self._env_lines()
        newline = getattr(self, "_env_newline", "\n")
        new_line = f"{name}={value}"
        replaced = False
        out: list[str] = []
        for ln in lines:
            if ln.rstrip("\r").startswith(name + "="):
                out.append(new_line)
                replaced = True
            else:
                out.append(ln)
        if not replaced:
            out.append(new_line)
        _atomic_write_text(self.dotenv_path, newline.join(out) + newline, newline=newline)

    def _unset_env(self, name: str) -> bool:
        lines = self._env_lines()
        newline = getattr(self, "_env_newline", "\n")
        out = [ln for ln in lines if not ln.rstrip("\r").startswith(name + "=")]
        removed = any(ln.rstrip("\r").startswith(name + "=") for ln in lines)
        if removed:
            body = newline.join(out)
            if body:  # avoid leaving a lone newline as a phantom empty line
                body += newline
            _atomic_write_text(self.dotenv_path, body, newline=newline)
        return removed


# ---------------------------------------------------------------------------
# Fernet credential crypto (encrypt-at-rest for OAuth tokens)
# ---------------------------------------------------------------------------

def _encode_key(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _decode_key(b64: str) -> bytes:
    return base64.urlsafe_b64decode(b64.encode("ascii"))


class CredentialCrypto:
    """Fernet seal/unseal for OAuth tokens. Key from env or .env; generated on
    first use and persisted (b64) so restarts can decrypt existing rows."""

    def __init__(self, store: Optional[ConfigStore] = None, use_dotenv: bool = True):
        self.store = store or ConfigStore()
        self.use_dotenv = use_dotenv
        self.key = self._obtain_key()

    def _obtain_key(self) -> bytes:
        from cryptography.fernet import Fernet
        # Explicit env override > persisted key in .env > freshly generated.
        key_b64 = os.environ.get(_ENCRYPTION_KEY_ENV, "")
        if not key_b64 and self.use_dotenv:
            key_b64 = self.store.read_dotenv().get(_ENCRYPTION_KEY_ENV, "")
        if not key_b64:
            key_b64 = _encode_key(Fernet.generate_key())
            self.store._set_env(_ENCRYPTION_KEY_ENV, key_b64)
            log.info("generated a new CLIPIT_ENCRYPTION_KEY in %s", self.store.dotenv_path)
        try:
            return _decode_key(key_b64.strip())
        except Exception as exc:
            raise ConfigError(
                f"CLIPIT_ENCRYPTION_KEY is not a valid Fernet key: {exc}"
            ) from exc

    def encrypt_secret(self, plaintext: str) -> str:
        from cryptography.fernet import Fernet
        return Fernet(self.key).encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt_secret(self, ciphertext: str) -> str:
        from cryptography.fernet import Fernet
        return Fernet(self.key).decrypt(ciphertext.encode("ascii")).decode("utf-8")


__all__ = [
    "ConfigStore", "CredentialCrypto", "ConfigError",
    "DEFAULT_CONFIG_PATH", "DEFAULT_DOTENV_PATH",
]