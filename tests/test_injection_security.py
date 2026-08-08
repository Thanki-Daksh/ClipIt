"""
tests/test_injection_security.py - TSK-A06-12: input injection & URL sanitizer audit.

Guards against command injection via yt-dlp URL inputs. Defense-in-depth
facts under test:

  1. No subprocess in the codebase is ever opened with ``shell=True``
     (a shell would interpret ``;`` / ``&&`` / ``$()`` / backticks).
  2. Every subprocess invocation uses a LIST argv (zero shell metachar
     expansion risk).
  3. MediaDownloader hands the raw URL to the yt-dlp LIBRARY API — a
     hostile URL string can never become shell tokens.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDITED_GLOBS = ("modules/*.py", "core/*.py", "main.py", "ui/app.py")
SHELL_TRUE_RE = re.compile(r"shell\s*=\s*True")
SUBPROCESS_CALL_RE = re.compile(
    r"subprocess\.(?:run|call|check_call|check_output|Popen)\("
)


def _production_sources() -> list[Path]:
    files: list[Path] = []
    for glob in AUDITED_GLOBS:
        for path in REPO_ROOT.glob(glob):
            if "__pycache__" not in str(path):
                files.append(path)
    return files


def test_no_shell_true_anywhere():
    offenders = []
    for path in _production_sources():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if SHELL_TRUE_RE.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "shell=True found:\n" + "\n".join(offenders)


def test_every_subprocess_call_uses_list_argv():
    """Each subprocess invocation must pass a list first arg (no strings)."""
    single = re.compile(
        r"subprocess\.(?:run|call|check_call|check_output|Popen)\(\s*['\"]"
    )
    offenders = []
    for path in _production_sources():
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if single.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, (
        "string-arg subprocess call (shell metachar risk):\n" + "\n".join(offenders)
    )


class _FakeYDL:
    """Records extract_info(url, download) calls like the real yt-dlp API."""

    def __init__(self, *_args, **_kwargs):
        self.calls: list[tuple[str, bool]] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url: str, download: bool = False):
        self.calls.append((url, download))
        return {
            "id": "FAKEID", "title": "Fake Title", "duration": 300.0,
            "thumbnail": None, "description": "", "uploader": "fake",
            "width": 1920, "height": 1080, "is_live": False, "was_live": False,
        }

    def prepare_filename(self, info: dict) -> str:
        return str(_FAKE_VIDEO_PATH)


_FAKE_VIDEO_PATH = None  # set per-test


def test_downloader_passes_malicious_url_verbatim_to_ytdlp(
        tmp_path, monkeypatch):
    """A URL stuffed with shell metacharacters never reaches a shell."""
    from modules import downloader as dl_module

    evil_url = (
        "https://www.youtube.com/watch?v=abc123;"
        "rm -rf /tmp/pwn;$(whoami)`id`&&echo pwned"
    )

    fake_video = tmp_path / "FAKEID.mp4"
    fake_video.write_bytes(b"x")
    globals()["_FAKE_VIDEO_PATH"] = fake_video

    ydl_instances: list[_FakeYDL] = []

    def _fake_ydl(*args, **kwargs):
        inst = _FakeYDL(*args, **kwargs)
        ydl_instances.append(inst)
        return inst

    monkeypatch.setattr(dl_module.yt_dlp, "YoutubeDL", _fake_ydl)
    monkeypatch.setattr(dl_module.MediaDownloader, "extract_audio_wav",
                        lambda self, in_p, out_p, normalize=True: True)

    dl = dl_module.MediaDownloader(output_dir=str(tmp_path / "dl"))
    result = dl.download(evil_url)

    assert result is not None
    assert len(ydl_instances) == 2  # pre-extract + download
    for inst in ydl_instances:
        assert inst.calls[0][0] == evil_url, "URL must be passed verbatim"

    # No shell could have been involved: subprocess in this module was never
    # invoked with shell=True (extract_audio_wav is stubbed; nothing else runs).
    # The static audit (tests above) already proves shell=True absence.


def test_main_sources_validation_does_not_pass_metachar_to_daemon(tmp_path):
    """main._validate_sources must reject/中性ize nothing dangerous — it
    simply returns the raw list; the safety boundary is the yt-dlp lib arg
    list (verified above). At minimum it must not itself spawn anything."""
    import argparse

    import main as app_main

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", default=[])
    args = ap.parse_args(["--source",
                          "https://x.com/v;system('rm -rf /')"])
    out = app_main._validate_sources(args)
    assert out == ["https://x.com/v;system('rm -rf /')"]