"""Ad-hoc secret sanitization audit for the ClipIt repo (Agent 06)."""
import os
import re
import pathlib

ROOT = pathlib.Path(r"C:\Users\Admin\OneDrive\Desktop\ClipIt")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".obsidian", "storage", "chunks_temp"}
SKIP_FILES = {"requirements.txt", "config.example.json", "pytest.ini"}

EX_PATTERNS = [
    (r"(?i)\b[A-Za-z0-9_]{2,}_API_KEY\s*[=:]\s*['\"][A-Za-z0-9\-_\.]{12,}", "API_KEY=..."),
    (r"\bsk-[A-Za-z0-9]{20,}", "OpenAI sk- token"),
    (r"\bAIza[0-9A-Za-z\-_]{35}", "Google AIza (Gemini)"),
    (r"\bgsk_[A-Za-z0-9]{20,}", "Groq gsk_ key"),
    (r"\bghp_[A-Za-z0-9]{30,}", "GitHub PAT"),
    (r"AKIA[0-9A-Z]{16}", "AWS AKIA"),
]
PLACEHOLDERS = {"YOUR_GROQ_API_KEY", "YOUR_GEMINI_API_KEY", "YOUR_OPENAI_API_KEY",
                "YOUR_API_KEY", "REPLACE_ME", "CHANGEME", "sk-xxxx"}

hits, db_files = [], []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
    for fn in filenames:
        full = pathlib.Path(dirpath) / fn
        rel = full.relative_to(ROOT)
        if fn.endswith((".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3")):
            db_files.append(str(rel))
        if fn in SKIP_FILES:
            continue
        if full.suffix.lower() in {".pyc", ".png", ".jpg", ".mp4", ".wav", ".gif"}:
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            for pat, label in EX_PATTERNS:
                m = re.search(pat, line)
                if m:
                    if any(ph in line for ph in PLACEHOLDERS):
                        continue
                    hits.append((str(rel), line_no, label, m.group(0)[:30]))

print("== SECURITY / SANITIZATION AUDIT: ClipIt ==")
print("Root:", ROOT, "\n")
print("[1] Production DB files in tree:")
print("   " + (", ".join(db_files) if db_files else "nil (good)"))
print("\n[2] Hardcoded API keys / secrets:")
if hits:
    for rel, ln, label, sec in hits:
        print("   %s:%s  (%s)  %s" % (rel, ln, label, sec))
else:
    print("   none found (good)")
print("\n[3] Placeholder-sentinel enforcement in core/config.py:",
      any(p in (ROOT / "core" / "config.py").read_text() for p in PLACEHOLDERS))
print("[4] .env present in repo:", (ROOT / ".env").exists())
existing_gitignored = ["storage/clipit.db", ".env", "__pycache__/"]
gi_file = ROOT / ".gitignore"
print("[5] .gitignore exists:", gi_file.exists())
if gi_file.exists():
    gi = gi_file.read_text()
    for entry in existing_gitignored:
        print("      ignore pattern %-30s %s" % (entry, "present" if entry in gi else "MISSING"))
else:
    print("      WARNING: no .gitignore -> .env / db / __pycache__ could be committed")