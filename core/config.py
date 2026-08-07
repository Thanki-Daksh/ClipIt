"""
ClipIt Configuration Loader
---------------------------
Parses `config.json` (project root) + `.env` (API keys) with strict
validation. Precedence: config.json < .env < process environment.

Strict validation guarantees:
  - API keys are present and not placeholder values
  - database_path resolves inside the project (no path traversal)
  - polling_interval_seconds is a positive number
  - max_daily_clips_per_account is a positive integer

Usage:
    from core.config import load_config
    cfg = load_config()
    cfg.groq_api_key, cfg.polling_interval_seconds, cfg.database_path
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.logger import get_logger

log = get_logger("config")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent  # ClipIt/
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"
DEFAULT_DOTENV_PATH = PROJECT_ROOT / ".env"

# Placeholder sentinel values that must never be accepted as real keys
_PLACEHOLDERS = {"", "YOUR_GROQ_API_KEY", "YOUR_GEMINI_API_KEY", "YOUR_OPENAI_API_KEY",
                 "YOUR_API_KEY", "REPLACE_ME", "CHANGEME", "sk-xxxx"}

# .env / environment variable names for API keys
_ENV_KEY_MAP = {
    "groq_api_key": "GROQ_API_KEY",
    "gemini_api_key": "GEMINI_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
}

# .env / environment variable names for runtime settings
_ENV_SETTING_MAP = {
    "database_path": "CLIPIT_DATABASE_PATH",
    "polling_interval_seconds": "CLIPIT_POLLING_INTERVAL_SECONDS",
    "max_daily_clips_per_account": "CLIPIT_MAX_DAILY_CLIPS_PER_ACCOUNT",
}


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid."""


@dataclass
class Config:
    groq_api_key: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    database_path: str = "storage/clipit.db"
    polling_interval_seconds: int = 300
    max_daily_clips_per_account: int = 3
    # resolved absolute path (set after load)
    resolved_db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "storage" / "clipit.db")

    # -- API key helpers ----------------------------------------------------
    def has_key(self, provider: str) -> bool:
        return bool(getattr(self, f"{provider}_api_key", ""))

    def require_key(self, provider: str) -> str:
        key = getattr(self, f"{provider}_api_key", "")
        if not key:
            raise ConfigError(
                f"Missing API key for provider '{provider}'. "
                f"Set {_ENV_KEY_MAP.get(f'{provider}_api_key', provider.upper() + '_API_KEY')} "
                "in .env or add it to config.json."
            )
        return key


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_valid_key(value: str) -> bool:
    """A key is valid if it is non-empty, not a placeholder, and looks key-ish."""
    if value is None:
        return False
    value = str(value).strip()
    if value in _PLACEHOLDERS:
        return False
    if len(value) < 8:
        return False
    # All known providers emit base64ish / alphanumeric keys
    return all(c.isalnum() or c in "-_." for c in value)


def _parse_dotenv(path: Path) -> dict:
    """Minimal .env parser (KEY=VALUE lines, # comments, quotes stripped)."""
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key] = value
    return result


def _load_json_config(path: Path) -> dict:
    """Load config.json; returns {} when the file is absent (keys may come from .env)."""
    if not path.exists():
        log.warning("config.json not found at %s — falling back to .env / defaults", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ConfigError(f"config.json at {path} must contain a JSON object")
        return data
    except json.JSONDecodeError as exc:
        raise ConfigError(f"config.json at {path} is not valid JSON: {exc}") from exc


# ---------------------------------------------------------------------------
# Main loader
# ---------------------------------------------------------------------------

def load_config(
    config_path: Optional[str | Path] = None,
    dotenv_path: Optional[str | Path] = None,
    require_api_keys: bool = True,
) -> Config:
    """
    Load and strictly validate ClipIt configuration.

    Args:
        config_path: explicit config.json path (defaults to <root>/config.json)
        dotenv_path: explicit .env path (defaults to <root>/.env)
        require_api_keys: raise if no provider key is configured (True for daemon)

    Raises:
        ConfigError: on missing/invalid required values.
    """
    cfg_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    env_path = Path(dotenv_path) if dotenv_path else DEFAULT_DOTENV_PATH

    file_cfg = _load_json_config(cfg_path)
    env_cfg = _parse_dotenv(env_path)

    cfg = Config()

    # --- API keys: config.json < .env < process env -----------------------
    for field_name, env_name in _ENV_KEY_MAP.items():
        value = file_cfg.get(field_name, "") or env_cfg.get(env_name, "") or os.environ.get(env_name, "")
        setattr(cfg, field_name, str(value).strip())

    # --- Runtime settings ---------------------------------------------------
    for field_name, env_name in _ENV_SETTING_MAP.items():
        value = file_cfg.get(field_name) or env_cfg.get(env_name) or os.environ.get(env_name)
        if value is not None and str(value).strip():
            setattr(cfg, field_name, str(value).strip())

    # --- Validation ---------------------------------------------------------
    errors: list[str] = []

    # database_path: must stay inside the project (no traversal)
    db_rel = Path(cfg.database_path)
    if db_rel.is_absolute():
        db_abs = db_rel
    else:
        db_abs = PROJECT_ROOT / db_rel
    try:
        db_abs = db_abs.resolve()
        db_abs.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"database_path '{cfg.database_path}' is not usable: {exc}")
    else:
        if not str(db_abs).startswith(str(PROJECT_ROOT.resolve())):
            errors.append(f"database_path must stay inside the project: {cfg.database_path}")
        else:
            cfg.resolved_db_path = db_abs

    # polling_interval_seconds
    try:
        cfg.polling_interval_seconds = int(cfg.polling_interval_seconds)
        if cfg.polling_interval_seconds <= 0:
            errors.append("polling_interval_seconds must be a positive integer")
    except (TypeError, ValueError):
        errors.append(f"polling_interval_seconds must be an integer, got '{cfg.polling_interval_seconds}'")

    # max_daily_clips_per_account
    try:
        cfg.max_daily_clips_per_account = int(cfg.max_daily_clips_per_account)
        if cfg.max_daily_clips_per_account <= 0:
            errors.append("max_daily_clips_per_account must be a positive integer")
    except (TypeError, ValueError):
        errors.append(
            f"max_daily_clips_per_account must be an integer, got '{cfg.max_daily_clips_per_account}'"
        )

    # API keys: at least one provider must be configured for daemon operation
    configured_providers = [p for p in ("groq", "gemini", "openai") if _is_valid_key(getattr(cfg, f"{p}_api_key"))]
    if require_api_keys and not configured_providers:
        errors.append(
            "No valid API key configured. Set GROQ_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY "
            f"in .env (at {env_path}) or config.json."
        )

    if errors:
        raise ConfigError("; ".join(errors))

    cfg.resolved_db_path = db_abs
    log.info(
        "config loaded: db=%s poll=%ss max_daily=%s providers=%s",
        cfg.resolved_db_path,
        cfg.polling_interval_seconds,
        cfg.max_daily_clips_per_account,
        ",".join(configured_providers) if configured_providers else "none",
    )
    return cfg


__all__ = ["Config", "ConfigError", "load_config", "DEFAULT_CONFIG_PATH", "PROJECT_ROOT"]
