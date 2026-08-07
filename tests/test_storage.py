"""
tests/test_storage.py - Account storage isolation (Agent 01 / TSK-A01-07).

Verifies that per-account directories never collide, are created lazily, are
guarded against path traversal, and that usage accounting works.
"""

from __future__ import annotations

from core.storage import AccountStorage, StorageError

SUB_DIRS = ("account", "raw", "audio", "clips", "ass", "outputs")


def _store(tmp_path):
    return AccountStorage(tmp_path / "accounts")


def test_layout_creates_all_subdirs(tmp_path):
    store = _store(tmp_path)
    layout = store.layout("acc_x")
    for name in SUB_DIRS:
        assert name in layout
        assert layout[name].is_dir()
    assert layout["raw"] == store.raw_dir("acc_x")
    assert layout["clips"] == store.clips_dir("acc_x")


def test_layout_is_idempotent(tmp_path):
    store = _store(tmp_path)
    first = store.layout("acc_y")
    second = store.layout("acc_y")
    assert first == second
    assert all(p.is_dir() for p in first.values())


def test_per_account_isolation(tmp_path):
    """Two accounts never share directories."""
    store = _store(tmp_path)
    a = store.layout("acc_a")
    b = store.layout("acc_b")
    for sub in ("raw", "clips", "audio", "outputs"):
        assert a[sub] != b[sub]
        assert str(a[sub]).startswith(str(a["account"]))
        assert str(b[sub]).startswith(str(b["account"]))


def test_account_usage_bytes_counts_files(tmp_path):
    store = _store(tmp_path)
    layout = store.layout("acc_c")
    (layout["raw"] / "v.mp4").write_bytes(b"x" * 1000)
    (layout["clips"] / "c.mp4").write_bytes(b"y" * 2000)
    assert store.account_usage_bytes("acc_c") == 3000


def test_path_traversal_guarded(tmp_path):
    store = _store(tmp_path)
    for evil in ("../escape", "a/b", "..", "a\\b"):
        try:
            store.account_dir(evil)
        except StorageError:
            pass  # expected
        else:
            raise AssertionError(f"unsafe id accepted: {evil!r}")


def test_list_accounts_only_existing(tmp_path):
    store = _store(tmp_path)
    store.layout("alpha")
    store.layout("beta")
    assert set(store.list_accounts()) == {"alpha", "beta"}


def test_wipe_account_removes_tree(tmp_path):
    store = _store(tmp_path)
    store.layout("w")
    assert store.wipe_account("w") is True
    assert "w" not in store.list_accounts()
    assert store.wipe_account("w") is False