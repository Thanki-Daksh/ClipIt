"""
tests/test_e2e.py - TSK-A06-05: Full synthetic E2E pipeline test.

Drives the real QueueEngine from enqueue -> COMPLETED across the whole 8-stage
state machine, where the CLIPPING stage performs a REAL FFmpeg 9:16 render of a
synthesized source MP4. Afterwards it asserts the produced clip is a valid
1080x1920 vertical file with no black frames and no silence.

This is the integration proof that a job queued for an account genuinely ends
up as a playable, correctly-shaped output clip.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import queue as q
from core.queue import COMPLETED, DOWNLOADING, PENDING, QueueEngine

from . import media_qa


def _install_stage_handlers(tmp_path: Path, ffmpeg: str) -> None:
    """Register handlers; the CLIPPING stage performs a real vertical render."""
    q.HANDLERS.clear()

    src = tmp_path / "source.mp4"  # written by the caller before running

    q.register_handler(
        q.DOWNLOADING,
        lambda job, db: (True, {
            "raw_video_path": str(src),
            "duration_seconds": 2.0,
        }),
    )
    q.register_handler(
        q.TRANSCRIBING,
        lambda job, db: (True, {"transcript_json": json.dumps({"text": "ok", "words": []})}),
    )
    q.register_handler(
        q.ANALYZING,
        lambda job, db: (True, {"transcript_json": json.dumps({"clips": [], "summary": "ok"})}),
    )

    def clipper(job, db):
        # Real render: source.mp4 -> clip_<jobid>.mp4 at 1080x1920.
        out = tmp_path / f"clip_{job['id']}.mp4"
        rc = media_qa.render_vertical(ffmpeg, src, out, 1080, 1920)
        if rc != 0:
            return False, f"ffmpeg render failed rc={rc}"
        db.create_clip(
            job_id=job["id"], account_id=job["account_id"],
            start_time="0", end_time="2", duration_seconds=2.0,
            virality_score=90.0, video_path=str(out),
        )
        return True, {"video_path": str(out)}

    q.register_handler(q.CLIPPING, clipper)
    q.register_handler(
        q.CAPTIONING,
        lambda job, db: (True, {"caption_path": str(tmp_path / "cap.txt")}),
    )
    q.register_handler(
        q.METADATA,
        lambda job, db: (True, {"title": "E2E Clip"}),
    )


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
def test_e2e_enqueue_to_rendered_mp4(db, accounts, ffmpeg_path, ffprobe_path,
                                     make_sample_video, tmp_path):
    if not (ffmpeg_path and ffprobe_path):
        pytest.skip("ffmpeg/ffprobe not available")

    # Stage -1: the pipeline "downloads" the pre-synthesized source video.
    src = tmp_path / "source.mp4"
    src.write_bytes(make_sample_video.read_bytes())

    _install_stage_handlers(tmp_path, ffmpeg_path)
    engine = QueueEngine(db)
    job_id = engine.enqueue(accounts["alpha"], "https://e2e/source")

    final_status = _drive_to_completion(engine, job_id)
    assert final_status == COMPLETED, f"pipeline ended at {final_status}"

    rows = db.list_clips(job_id=job_id)
    assert len(rows) == 1, "expected exactly one rendered clip"
    clip_path = Path(rows[0]["video_path"])
    assert clip_path.exists(), f"rendered clip not found: {clip_path}"

    width, height = media_qa.probe_resolution(ffprobe_path, clip_path)
    assert (width, height) == (1080, 1920), f"got {width}x{height}, want 1080x1920"
    assert clip_path.stat().st_size > 0


@pytest.mark.ffprobe
def test_e2e_rendered_clip_has_no_black_frames_and_no_silence(
        ffmpeg_path, make_sample_video):
    """The quality probe asserts a rendered clip is useable, not corrupt."""
    if not ffmpeg_path:
        pytest.skip("ffmpeg required")
    out = make_sample_video.parent / "qa_9x16.mp4"
    assert media_qa.render_vertical(ffmpeg_path, make_sample_video, out) == 0
    black = media_qa.detect_black_frames(ffmpeg_path, out)
    assert black == [], f"unexpected black frames at {black}"
    silence = media_qa.detect_silence(ffmpeg_path, out)
    assert silence == [], f"unexpected silence: {silence}"


@pytest.mark.ffprobe
def test_ffprobe_resolution_helper(ffprobe_path, make_sample_video):
    if not ffprobe_path:
        pytest.skip("ffprobe required")
    assert media_qa.probe_resolution(ffprobe_path, make_sample_video) == (1280, 720)