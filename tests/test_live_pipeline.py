"""
tests/test_live_pipeline.py - TSK-A06-09: live video processing integration.

Drives the REAL Agent 03 render pipeline (VideoClipper vertical crop, ASS
subtitle generation + FFmpeg burn-in, MetadataCompiler packaging) through the
QueueEngine across the whole working pipeline. Only the network/credential
stages (downloader, transcriber, analyzer) are stubbed — the media-processing
stages are the genuine production modules operating on a synthesized source.

Asserts the end-to-end result the business cares about:
  - a job enqueued for an account ends COMPLETED
  - a real 1080x1920 vertical clip is rendered to the account clip dir
  - an .ass caption file is produced and burned into the final clip
  - a metadata.json export package is written to outputs/
  - the final clip passes the black-frame probe (not a corrupt render)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import queue as q
from core.queue import COMPLETED, DOWNLOADING, PENDING, QueueEngine
from core.storage import AccountStorage
from core.workers import _make_clipper, _make_captioner, _make_metadata

from . import media_qa


# ---------------------------------------------------------------------------
# A synthesized ~6s 16:9 source (clipper enforces a 5s minimum clip length).
# ---------------------------------------------------------------------------

def _make_source(ffmpeg: str, out: Path) -> Path:
    import subprocess
    subprocess.run([
        ffmpeg, "-y",
        "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=24:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", str(out),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return out


def _install_real_media_handlers(tmp_path: Path, store: AccountStorage,
                                 ffmpeg: str) -> None:
    """Register the real clipper/captioner/metadata + canned network stages."""
    q.HANDLERS.clear()

    from modules.clipper import VideoClipper
    from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer
    from modules.metadata import MetadataCompiler

    cfg = type("Cfg", (), {"resolved_db_path": tmp_path / "x.db"})()
    src_path = _make_source(ffmpeg, tmp_path / "source_6s.mp4")

    # DOWNLOADING: simulate "live intake" — reuse the already-present source.
    q.register_handler(q.DOWNLOADING, lambda job, db: (True, {
        "raw_video_path": str(src_path),
        "audio_path": str(tmp_path / "audio.wav"),
        "duration_seconds": 6.0,
        "title": "Live intake clip",
    }))
    # TRANSCRIBING: canned word-timestamps covered by the 0-6s source.
    def transcribe(job, db):
        words = [{"word": f"w{i}", "start": i * 0.5, "end": i * 0.5 + 0.5}
                 for i in range(10)]
        return True, {"transcript_json": json.dumps({"words": words})}
    q.register_handler(q.TRANSCRIBING, transcribe)

    # ANALYZING: one 0.5-5.5s candidate clip (>=5s to satisfy clipper minimum).
    def analyze(job, db):
        db.create_clip(
            job_id=job["id"], account_id=job["account_id"],
            start_time="0.5", end_time="5.5", duration_seconds=5.0,
            virality_score=92.0, hook_text="Opening hook",
            title="Viral Hook", description="#tech #clip",
            hashtags="#tech #clip",
        )
        return True, {"transcript_json": job["transcript_json"]}
    q.register_handler(q.ANALYZING, analyze)

    # Real media stages.
    q.register_handler(q.CLIPPING, _make_clipper(cfg, store, VideoClipper))
    q.register_handler(q.CAPTIONING, _make_captioner(
        cfg, store, ASSSubtitleGenerator, SubtitleRenderer))
    q.register_handler(q.METADATA, _make_metadata(cfg, store, MetadataCompiler))


@pytest.fixture(autouse=True)
def clean_handlers():
    q.HANDLERS.clear()
    yield
    q.HANDLERS.clear()


def _drive_to_completion(engine: QueueEngine, job_id: str) -> str:
    job = engine.db.get_job(job_id)
    status = job["status"]
    if status == PENDING:
        engine.transition(job_id, q.DOWNLOADING)
        status = q.DOWNLOADING
    for _ in range(12):
        if status not in q.WORKING_STAGES:
            break
        status = engine.run_job(engine.db.get_job(job_id))
    return status


@pytest.mark.ffprobe
@pytest.mark.e2e
def test_live_pipeline_produces_captioned_1080x1920_clip(
        db, accounts, tmp_path, ffmpeg_path, ffprobe_path):
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe required")

    store = AccountStorage(tmp_path / "accounts")
    _install_real_media_handlers(tmp_path, store, ffmpeg_path)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["alpha"], "https://live/intake")
    final = _drive_to_completion(engine, job_id)
    assert final == COMPLETED, f"ended at {final}"

    rows = db.list_clips(job_id=job_id)
    assert len(rows) == 1, f"expected 1 clip, got {len(rows)}"
    clip = rows[0]

    # Real render artifacts on disk in the account-isolated dir.
    final_video = Path(clip["video_path"])
    ass = Path(clip["caption_path"])
    assert final_video.exists() and final_video.stat().st_size > 0
    assert ass.exists() and "Dialogue:" in ass.read_text()

    # 9:16 spec + not a black render.
    width, height = media_qa.probe_resolution(ffprobe_path, final_video)
    assert (width, height) == (1080, 1920), f"got {width}x{height}"
    assert media_qa.detect_black_frames(ffmpeg_path, final_video) == []

    # Metadata package staged in outputs/ for the auto-poster.
    out_dir = store.outputs_dir(accounts["alpha"])
    meta_file = out_dir / "metadata.json"
    assert meta_file.exists(), f"metadata.json missing: {meta_file}"
    meta = json.loads(meta_file.read_text())
    assert meta["clip_id"]
    assert meta["title"]
    assert meta["hashtags"]  # non-empty


def test_live_pipeline_account_storage_isolated(tmp_path):
    """Per-account dirs (raw/audio/clips/ass/outputs) are created & isolated."""
    store = AccountStorage(tmp_path / "accounts")
    layout = store.layout("acc_a")
    for sub in ("raw", "audio", "clips", "ass", "outputs"):
        assert layout[sub].exists()
    # Second account must not collide.
    other = store.layout("acc_b")
    assert str(other["clips"]) != str(layout["clips"])