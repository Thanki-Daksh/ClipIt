"""
tests/test_security.py - TSK-A06-07: codebase secret sanitization gate.

The core assertion is that the committed ClipIt repository contains ZERO
hardcoded API keys and ZERO production database files. A synthetic tmp tree
with a baked-in fake key proves the scanner actually catches secrets (so a green
result is meaningful, not vacuous).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from . import secret_sanitizer as ss


def test_repo_is_clean_of_secrets():
    """The whole project must scan clean. Allowed: placeholder values only."""
    findings = ss.scan_project()
    assert findings == [], "\n".join(
        f"  {f.path}:{f.line}  {f.kind}  ({f.value_preview})" for f in findings
    )


def test_repo_has_no_database_files():
    findings = [f for f in ss.scan_project() if f.kind == "database_file"]
    assert findings == []


def test_scanner_detects_google_gemini_key(tmp_path):
    fake = tmp_path / "leak.py"
    fake.write_text(f"GEMINI_API_KEY = \"AIza{'A'*40}\"\n")
    findings = ss.scan_paths([fake])
    kinds = {f.kind for f in findings}
    assert "Google Gemini API key" in kinds


def test_scanner_detects_groq_key(tmp_path):
    fake = tmp_path / "g.py"
    fake.write_text(f"GROQ_API_KEY = gsk_{'q'*30}\n")
    findings = ss.scan_paths([fake])
    assert any("Groq API key" in f.kind for f in findings)


def test_scanner_detects_openai_sk_key(tmp_path):
    fake = tmp_path / "sneaky.env"
    fake.write_text(f"OPENAI_API_KEY=sk-{'r'*40}\n")
    findings = ss.scan_paths([fake])
    assert any("OpenAI API key" in f.kind for f in findings)


def test_scanner_detects_db_file(tmp_path):
    fake_db = tmp_path / "clipit.db"
    fake_db.write_bytes(b"\x00\x01fake")
    findings = ss.scan_paths([tmp_path])
    assert any(f.kind == "database_file" for f in findings)


def test_placeholder_value_is_allowed(tmp_path):
    fake = tmp_path / "cfg.json"
    fake.write_text('{"groq_api_key": "YOUR_GROQ_API_KEY"}\n')
    assert ss.scan_paths([fake]) == []


def test_scanner_skips_ignored_dirs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret.txt").write_text(f"ghp_{'z'*32}\n")
    assert ss.scan_project(tmp_path) == []