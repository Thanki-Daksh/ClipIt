"""
tests/test_oauth_credentials.py - OAuth credential store (TSK-A01-10).

Verifies the oauth_credentials table (SCHEMA_VERSION 2) CRUD: upsert,
get, list, revoke (soft), delete, and the account/provider unique constraint.
"""

from __future__ import annotations

import pytest

from core.db import SCHEMA_VERSION


def _with_account(db, account_id="acc_alpha"):
    """Ensure an account exists for credential tests."""
    if not db.get_account(account_id):
        db.create_account(account_id, account_id, "nickname", sources=[])
    return account_id


def test_schema_version_is_two(db):
    conn = db._conn()
    assert conn.execute("PRAGMA user_version;").fetchone()[0] == SCHEMA_VERSION == 2


def test_oauth_table_exists(db):
    conn = db._conn()
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "oauth_credentials" in names


def test_upsert_and_get(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(
        acc, "youtube",
        access_token_enc="ENC_AT", refresh_token_enc="ENC_RT", scopes="youtube.upload",
    )
    row = db.get_oauth_credential(acc, "youtube")
    assert row is not None
    assert row["access_token_enc"] == "ENC_AT"
    assert row["refresh_token_enc"] == "ENC_RT"


def test_upsert_updates_in_place_not_duplicate(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(acc, "youtube", access_token_enc="AT_V1")
    db.upsert_oauth_credential(acc, "youtube", access_token_enc="AT_V2")
    rows = db.list_oauth_credentials("youtube")
    matching = [r for r in rows if r["account_id"] == acc and r["provider"] == "youtube"]
    assert len(matching) == 1
    assert matching[0]["access_token_enc"] == "AT_V2"


def test_unique_account_provider(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(acc, "instagram", access_token_enc="IG_AT")
    # different provider on same account is allowed
    db.upsert_oauth_credential(acc, "youtube", access_token_enc="YT_AT")
    assert len(db.list_oauth_credentials()) == 2


def test_revoke_hides_but_keeps_row(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(acc, "youtube", access_token_enc="ENC_AT")
    assert db.revoke_oauth_credential(acc, "youtube") is True
    # revoked rows are excluded from the active getter
    assert db.get_oauth_credential(acc, "youtube") is None
    # but still present in a direct provider listing
    rows = db.list_oauth_credentials("youtube")
    yt = [r for r in rows if r["account_id"] == acc][0]
    assert yt["revoked"] == 1


def test_delete_removes_row(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(acc, "instagram", access_token_enc="IG")
    assert db.delete_oauth_credential(acc, "instagram") is True
    assert db.delete_oauth_credential(acc, "instagram") is False
    assert db.get_oauth_credential(acc, "instagram") is None


def test_bad_provider_rejected(db):
    acc = _with_account(db)
    with pytest.raises(ValueError):
        db.upsert_oauth_credential(acc, "tiktok", access_token_enc="X")


def test_unknown_account_rejected(db, accounts):
    with pytest.raises(ValueError):
        db.upsert_oauth_credential("no_such_account", "youtube", access_token_enc="X")


def test_cascade_delete_on_account_removal(db):
    acc = _with_account(db)
    db.upsert_oauth_credential(acc, "youtube", access_token_enc="ENC")
    db.upsert_oauth_credential(acc, "instagram", access_token_enc="IG")
    db.delete_account(acc)
    assert db.list_oauth_credentials() == []