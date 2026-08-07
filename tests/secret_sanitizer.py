"""
tests/secret_sanitizer.py - TSK-A06-07: reusable codebase secret scanner.

Scans a directory tree for hardcoded API keys, tokens, and production DB files
that must never be committed. Designed to be run:
  - as a QA gate from pytest (see test_security.py), and
  - standalone:  python -m pytest tests/test_security.py
Returns a list of Finding objects; empty list == clean.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Placeholder strings that ARE allowed (config.example.json, tests, docs).
SAFE_PLACEHOLDERS = (
    "YOUR_GROQ_API_KEY", "YOUR_GEMINI_API_KEY", "YOUR_OPENAI_API_KEY",
    "YOUR_API_KEY", "REPLACE_ME", "CHANGEME", "sk-xxxx",
)

# High-signal secret shapes: (regex, human-readable kind)
SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}"),                 "Google Gemini API key"),
    (re.compile(r"\bgsk_[0-9A-Za-z]{24,}"),                    "Groq API key"),
    (re.compile(r"\bsk-[0-9A-Za-z]{32,}"),                     "OpenAI API key"),
    (re.compile(r"\bghp_[0-9A-Za-z]{30,}"),                    "GitHub personal token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}"),                        "AWS access key id"),
    (re.compile(r"(?i)api[_-]?key\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}"),   "api key assignment"),
    (re.compile(r"(?i)secret\s*[=:]\s*['\"][A-Za-z0-9_\-]{12,}"),        "secret assignment"),
]

DB_EXTENSIONS = {".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"}
BINARY_EXTENSIONS = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".mp4", ".wav", ".tmp"}


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    value_preview: str


def _is_allowed(line: str) -> bool:
    """True when a line only contains an explicit placeholder value."""
    lowered = line.lower()
    return any(ph.lower() in lowered for ph in SAFE_PLACEHOLDERS)


def scan_paths(paths: list[Path],
               skip_dirs: set[str] | None = None) -> list[Finding]:
    """Recursively scan `paths` for secrets / DB files. Returns findings."""
    skip_dirs = skip_dirs or {".git", "__pycache__", "node_modules", ".venv",
                              "venv", ".obsidian", "storage", ".pytest_cache"}
    findings: list[Finding] = []

    def walk(d: Path) -> None:
        for child in d.iterdir():
            if child.is_dir():
                if child.name not in skip_dirs:
                    walk(child)
            else:
                _scan_file(child, findings)

    for p in paths:
        if p.is_dir():
            walk(p)
        else:
            _scan_file(p, findings)
    return findings


def _scan_file(path: Path, findings: list[Finding]) -> None:
    # 1) Live database files — never commit.
    if _is_db_file(path):
        findings.append(Finding(str(path), 0, "database_file", path.name))
        return

    # 2) Binary files: skip.
    if path.suffix.lower() in BINARY_EXTENSIONS:
        return

    # 3) Text-ish files: scan line by line.
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return
    for i, line in enumerate(lines, 1):
        if _is_allowed(line):
            continue
        for regex, kind in SECRET_PATTERNS:
            match = regex.search(line)
            if match:
                findings.append(Finding(str(path), i, kind, match.group(0)[:20]))
                break  # one finding per line keeps the report compact


def _is_db_file(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(ext) for ext in DB_EXTENSIONS)


def scan_project(root: Path | None = None,
                 skip_dirs: set[str] | None = None) -> list[Finding]:
    """Scan the ClipIt project root (defaults to repo root = tests/..)."""
    if root is None:
        root = Path(__file__).resolve().parent.parent
    return scan_paths([root], skip_dirs=skip_dirs)