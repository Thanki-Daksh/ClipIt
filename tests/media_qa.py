"""
tests/media_qa.py - Shared media QA probing helpers for ClipIt (Agent 06).

Wraps FFmpeg/FFprobe subprocess probes used by the E2E and black-frame/silence
test suites:

  - run_ffmpeg         : invoke ffmpeg with args, capture rc/out/err.
  - probe_resolution   : (width, height) of a video stream via ffprobe.
  - render_vertical    : 9:16 crop of a source to [1080x1920] via -vf chain.
  - detect_black_frames: uses ffmpeg `signalstats` -> luma (YAVG) per frame;
                         any frame below `black_luma` is a corrupted black frame.
  - detect_silence     : uses ffmpeg `silencedetect` -> silence periods >= min.
  - extract_keyframe   : grab a mid frame as PNG (vision probe support).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

BLACK_LUMA_THRESHOLD = 16.0  # YAVG below this = essentially a black frame
SILENCE_NOISE_DB = -35.0     # silence threshold in dBFS
SILENCE_MIN_SECONDS = 0.40   # only report silence runs >= this long


def run_ffmpeg(binary: str, args: list[str]) -> tuple[int, str, str]:
    """Run ffmpeg/ffprobe; return (returncode, stdout, stderr)."""
    proc = subprocess.run(
        [binary, *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout.decode("utf-8", errors="replace"), \
        proc.stderr.decode("utf-8", errors="replace")


def probe_resolution(ffprobe: str, video_path: Path) -> tuple[int, int]:
    """Return (width, height) of a video stream via ffprobe, or (0, 0)."""
    rc, out, _ = run_ffmpeg(ffprobe, [
        "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video_path),
    ])
    if rc != 0:
        return 0, 0
    parts = out.strip().split(",")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return 0, 0
    return 0, 0


def render_vertical(ffmpeg: str, source: Path, output: Path,
                    width: int = 1080, height: int = 1920) -> int:
    """Render a 9:16 vertical clip from `source`. Returns ffmpeg return code."""
    filt = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    return run_ffmpeg(ffmpeg, [
        "-y", "-i", str(source), "-vf", filt,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", str(output),
    ])[0]


def detect_black_frames(ffmpeg: str, video_path: Path,
                        threshold: float = BLACK_LUMA_THRESHOLD) -> list[float]:
    """
    Return a list of timestamps (seconds) whose frame luma (YAVG) is <= threshold.
    Uses ffmpeg `signalstats` + `metadata=print` which writes `lavfi.signalstats.YAVG`
    on stdout. An empty list = no black frames.
    """
    rc, out, _ = run_ffmpeg(ffmpeg, [
        "-i", str(video_path),
        "-vf", "signalstats,metadata=print:file=-",
        "-f", "null", "-",
    ])
    if rc != 0:
        return []
    black_frames: list[float] = []
    current_ts = 0.0
    for line in out.splitlines():
        line = line.strip()
        ts_m = re.search(r"pts_time:([0-9.]+)", line)
        if ts_m:
            current_ts = float(ts_m.group(1))
        yavg_m = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", line)
        if yavg_m and float(yavg_m.group(1)) <= threshold:
            black_frames.append(round(current_ts, 3))
    return black_frames


def detect_silence(ffmpeg: str, media_path: Path,
                   noise_db: float = SILENCE_NOISE_DB,
                   min_seconds: float = SILENCE_MIN_SECONDS,
                   ) -> list[tuple[float, float]]:
    """
    Return silence periods as [(start_seconds, duration_seconds), ...] using
    ffmpeg `silencedetect`. Empty list = no silence longer than min_seconds.
    """
    rc, _, err = run_ffmpeg(ffmpeg, [
        "-i", str(media_path),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_seconds}",
        "-f", "null", "-",
    ])
    if rc != 0:
        return []
    periods: list[tuple[float, float]] = []
    start: float | None = None
    for line in err.splitlines():
        s = re.search(r"silence_start:\s*([0-9.]+)", line)
        e = re.search(r"silence_end:\s*([0-9.]+)", line)
        if s:
            start = float(s.group(1))
        elif e and start is not None:
            periods.append((round(start, 3), round(float(e.group(1)) - start, 3)))
            start = None
    return periods


def extract_keyframe(ffmpeg: str, video_path: Path, out_png: Path,
                     seek: float = 0.0) -> bool:
    """Extract a keyframe PNG at ~`ts` seconds. Returns success."""
    rc, _, _ = run_ffmpeg(ffmpeg, [
        "-y", "-ss", str(seek), "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", str(out_png),
    ])
    return rc == 0 and out_png.exists() and out_png.stat().st_size > 0


def probe_streams(ffprobe: str, media_path: Path) -> list[dict]:
    """
    Return per-stream ffprobe info: codec_type, codec_name, width, height,
    duration, start_time. Used for h264/aac codec sanity (TSK-A06-04) and
    audio/video sync checks (TSK-A06-10).
    """
    import json
    rc, out, _ = run_ffmpeg(ffprobe, [
        "-v", "error", "-show_entries",
        "stream=index,codec_type,codec_name,width,height,duration,start_time",
        "-of", "json", str(media_path),
    ])
    if rc != 0:
        return []
    try:
        return (json.loads(out).get("streams") or [])
    except json.JSONDecodeError:
        return []