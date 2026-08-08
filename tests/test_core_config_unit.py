"""
tests/test_core_config_unit.py - TSK-A06-01 completion: core/config + logger.

Focused unit tests for the config loader contract:
  * precedence: config.json < .env < process environment
  * placeholder values are rejected / treated as missing
  * .env parser handles quotes, inline comments, blank lines
  * database_path traversal guard (must stay inside the project)
  * logger factory returns a real logging.Logger
"""

from __future__ import annotations

import json
import logging

import pytest

from core.config import ConfigError, load_config
from core.logger import get_logger


def _write_config(tmp_path, data: dict) -> str:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def _no_dotenv(tmp_path) -> str:
    path = tmp_path / ".env"
    path.write_text("", encoding="utf-8")
    return str(path)


def test_file_values_loaded(tmp_path):
    cfg = load_config(
        config_path=_write_config(tmp_path, {
            "groq_api_key": "file-key-groq",
            "database_path": "storage/t.db",
        }),
        dotenv_path=_no_dotenv(tmp_path),
        require_api_keys=False,
    )
    assert cfg.groq_api_key == "file-key-groq"


def test_dotenv_overrides_config_json(tmp_path):
    cfg = load_config(
        config_path=_write_config(tmp_path, {
            "groq_api_key": "file-key-groq",
        }),
        dotenv_path=str(tmp_path / "no.env"),  # nonexistent -> empty
        require_api_keys=False,
    )
    # dotenv file missing -> file value survives
    assert cfg.groq_api_key == "file-key-groq"

    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=dotenv-key-groq\n", encoding="utf-8")
    cfg = load_config(
        config_path=_write_config(tmp_path, {
            "groq_api_key": "file-key-groq",
        }),
        dotenv_path=str(env_file),
        require_api_keys=False,
    )
    assert cfg.groq_api_key == "dotenv-key-groq"


def test_process_env_wins_over_all(monkeypatch, tmp_path):
    monkeypatch.setenv("GROQ_API_KEY", "env-key-groq")
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=dotenv-key-groq\n", encoding="utf-8")
    cfg = load_config(
        config_path=_write_config(tmp_path, {
            "groq_api_key": "file-key-groq",
        }),
        dotenv_path=str(env_file),
        require_api_keys=False,
    )
    assert cfg.groq_api_key == "env-key-groq"


def test_placeholder_keys_are_invalid(tmp_path):
    """_is_valid_key must reject the shipped placeholder sentinels so
    require_api_keys=True fails instead of silently trusting them."""
    from core.config import _is_valid_key
    for bad in ("YOUR_GROQ_API_KEY", "YOUR_GEMINI_API_KEY", "sk-xxxx", "REPLACE_ME", ""):
        assert not _is_valid_key(bad), f"placeholder {bad!r} must be invalid"
    assert _is_valid_key("valid-key-123456789")


def test_require_api_keys_raises_when_none_valid(tmp_path):
    with pytest.raises(ConfigError):
        load_config(
            config_path=_write_config(tmp_path, {
                "groq_api_key": "YOUR_GROQ_API_KEY",
            }),
            dotenv_path=_no_dotenv(tmp_path),
            require_api_keys=True,
        )


def test_dotenv_parser_handles_quotes_comments_and_blanks(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment line\n"
        "\n"
        'GROQ_API_KEY="quoted-key"\n'
        "GEMINI_API_KEY=spaced-key   \n"
        "CLIPIT_POLLING_INTERVAL_SECONDS=120\n",
        encoding="utf-8",
    )
    cfg = load_config(
        config_path=_write_config(tmp_path, {}),
        dotenv_path=str(env_file),
        require_api_keys=False,
    )
    assert cfg.groq_api_key == "quoted-key"
    assert cfg.gemini_api_key == "spaced-key"
    assert cfg.polling_interval_seconds == 120


def test_database_path_must_stay_inside_project(tmp_path):
    with pytest.raises(ConfigError, match="inside the project"):
        load_config(
            config_path=_write_config(tmp_path, {
                "database_path": "../../../etc/evil.db",
            }),
            dotenv_path=_no_dotenv(tmp_path),
            require_api_keys=False,
        )


def test_db_synchronous_validated(tmp_path):
    with pytest.raises(ConfigError, match="db_synchronous"):
        load_config(
            config_path=_write_config(tmp_path, {"db_synchronous": "BOGUS"}),
            dotenv_path=_no_dotenv(tmp_path),
            require_api_keys=False,
        )


def test_get_logger_returns_standard_logger():
    log = get_logger("qa-unit")
    assert isinstance(log, logging.Logger)
    assert log.name == "core.qa-unit"  # namespaced under the core package
