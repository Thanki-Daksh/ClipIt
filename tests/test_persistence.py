"""
tests/test_persistence.py - API key & config persistence engine (TSK-A01-11).

Verifies atomic .env/config.json writes (set/unset), masked reads, CRLF
preservation, invalid-key rejection, and Fernet round-trips for OAuth tokens.
"""

from __future__ import annotations

import json

import pytest

from core.config import ConfigError
from core.persistence import ConfigStore, CredentialCrypto


@pytest.fixture
def store(tmp_path) -> ConfigStore:
    return ConfigStore(config_path=tmp_path / "config.json", dotenv_path=tmp_path / ".env")


# ---------------------------------------------------------------------------
# .env API key persistence
# ---------------------------------------------------------------------------

def test_set_and_read_api_key(store):
    store.set_api_key("groq", "gsk_AbCdEfGhIjKlMnOpQrStUvWxYz")  # YOUR_GROQ_API_KEY
    assert store.api_key("groq") == "gsk_AbCdEfGhIjKlMnOpQrStUvWxYz"  # YOUR_GROQ_API_KEY


def test_set_key_updates_existing_line(store):
    store.set_api_key("gemini", "AIzaSyFirstKey1234567890abcdef")
    store.set_api_key("gemini", "AIzaSySecondKey1234567890abcdef")
    lines = store.dotenv_path.read_text(encoding="utf-8").splitlines()
    matching = [ln for ln in lines if ln.startswith("GEMINI_API_KEY=")]
    assert len(matching) == 1
    assert matching[0] == "GEMINI_API_KEY=AIzaSySecondKey1234567890abcdef"


def test_unset_api_key(store):
    store.set_api_key("openai", "sk-1234567890abcdefghijklmnopqrstuvwxyz")  # YOUR_OPENAI_API_KEY
    assert store.unset_api_key("openai") is True
    assert store.api_key("openai") == ""
    assert store.unset_api_key("openai") is False


def test_invalid_key_rejected(store):
    for bad in ("", "short", "YOUR_GROQ_API_KEY", "sk-xxxx"):
        with pytest.raises(ConfigError):
            store.set_api_key("groq", bad)


def test_unknown_provider_rejected(store):
    with pytest.raises(ValueError):
        store.set_api_key("nope", "abcdefghijklmnopqrstuvwxyz123456")


def test_crlf_preserved(store):
    store.dotenv_path.write_text("GROQ_API_KEY=oldkey1234567890\r\nFOO=bar\r\n",
                                 encoding="utf-8")
    store.set_api_key("groq", "gsk_NewKey1234567890")
    raw = store.dotenv_path.read_bytes()
    assert b"\r\n" in raw
    lines = store.dotenv_path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "GROQ_API_KEY=gsk_NewKey1234567890"


# ---------------------------------------------------------------------------
# config.json settings persistence
# ---------------------------------------------------------------------------

def test_set_setting_roundtrip(store):
    store.set_setting("polling_interval_seconds", 120)
    store.set_setting("max_daily_clips_per_account", 7)
    data = json.loads(store.config_path.read_text(encoding="utf-8"))
    assert data["polling_interval_seconds"] == 120
    assert data["max_daily_clips_per_account"] == 7


def test_set_setting_merges_not_clobbers(store):
    store.set_setting("a", 1)
    store.set_setting("b", 2)
    data = json.loads(store.config_path.read_text(encoding="utf-8"))
    assert data == {"a": 1, "b": 2}


def test_unset_setting(store):
    store.set_setting("a", 1)
    assert store.unset_setting("a") is True
    assert json.loads(store.config_path.read_text(encoding="utf-8")) == {}
    assert store.unset_setting("a") is False


# ---------------------------------------------------------------------------
# Fernet credential crypto
# ---------------------------------------------------------------------------

def test_encrypt_decrypt_roundtrip(store):
    crypto = CredentialCrypto(store=store)
    token = "ya29.a0AfH6SMC-very-secret-oauth-token"
    enc = crypto.encrypt_secret(token)
    assert enc != token and token not in enc
    assert crypto.decrypt_secret(enc) == token


def test_key_persisted_to_dotenv(store):
    crypto = CredentialCrypto(store=store)
    assert "CLIPIT_ENCRYPTION_KEY" in store.read_dotenv()
    assert crypto.key == CredentialCrypto(store=store).key  # stable across restarts


def test_second_instance_decrypts(store):
    first = CredentialCrypto(store=store)
    enc = first.encrypt_secret("roundtrip-token")
    second = CredentialCrypto(store=store)
    assert second.decrypt_secret(enc) == "roundtrip-token"


def test_bad_encryption_key_raises(store, monkeypatch):
    monkeypatch.setenv("CLIPIT_ENCRYPTION_KEY", "not-a-valid-fern-et-key!!")
    with pytest.raises(ConfigError):
        CredentialCrypto(store=store)