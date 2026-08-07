"""
ClipIt Worker Adapters (Agent 01)
---------------------------------
Bridges the QueueEngine handler contract ``(job_row, db) -> (ok, detail)`` to
the real worker modules owned by Agent 02 (downloader, transcriber, analyzer)
and Agent 03 (clipper, captioner, metadata).

Storage isolation: every handler writes through :class:`AccountStorage` so raw
video, audio, clips, captions and outputs stay inside ``storage/{account_id}/``.

Handlers never raise: worker exceptions are caught and returned as an
``(False, error)`` tuple so the queue engine applies retry -> fail semantics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

from core.config import Config
from core.db import Database
from core.logger import get_logger
from core.queue import (
    ANALYZING, CAPTIONING, CLIPPING, DOWNLOADING, METADATA, TRANSCRIBING,
    register_handler,
)
from core.storage import AccountStorage

log = get_logger("workers")
Handler = Callable[[Any, Database], tuple[bool, Any]]


def _import(module_name: str, member: str):
    """Return a worker class from a module, or None if unavailable."""
    try:
        module = __import__(module_name, fromlist=[member])
        return getattr(module, member)
    except Exception as exc:
        log.info("worker %s.%s not loadable: %s", module_name, member, exc)
        return None


def _words_in_window(transcript_json: str, start: float, end: float) -> list[dict]:
    """Flatten word timestamps from a transcript that fall inside a clip window."""
    if not transcript_json:
        return []
    try:
        data = json.loads(transcript_json)
    except (json.JSONDecodeError, TypeError):
        return []
    out: list[dict] = []
    for w in data.get("words", []):
        ws, we = float(w.get("start", 0.0)), float(w.get("end", w.get("start", 0.0)))
        if ws >= start and we <= end:
            out.append({"word": w.get("word", w.get("text", "")), "start": ws, "end": we})
    return out


# ---------------------------------------------------------------------------
# Stage handler factories
# ---------------------------------------------------------------------------

def _make_downloader(cfg: Config, store: AccountStorage, MediaDownloader) -> Handler:
    def handler(job, db):
        try:
            dl = MediaDownloader(output_dir=str(store.raw_dir(job["account_id"])))
            result = dl.download(job["source_url"])
            raw_name = Path(result.video_path).name
            audio_name = Path(result.audio_path).name
            return True, {
                "raw_video_path": str(store.raw_dir(job["account_id"]) / raw_name),
                "audio_path": str(store.audio_dir(job["account_id"]) / audio_name),
                "duration_seconds": float(result.duration),
                "title": result.title,
            }
        except Exception as exc:
            return False, f"downloader: {type(exc).__name__}: {exc}"
    return handler


def _make_transcriber(cfg: Config, store: AccountStorage, WhisperTranscriber) -> Handler:
    def handler(job, row):
        try:
            audio = job["audio_path"]
            if not audio or not Path(audio).exists():
                return False, f"transcriber: audio_path not found ({audio})"
            tr = WhisperTranscriber(api_key=cfg.require_key("groq"), provider="groq")
            result = tr.transcribe(audio)
            return True, {"transcript_json": result.model_dump_json()}
        except Exception as exc:
            return False, f"transcriber: {type(exc).__name__}: {exc}"
    return handler


def _make_analyzer(cfg: Config, store: AccountStorage, ViralityAnalyzer) -> Handler:
    def handler(job, db):
        try:
            if not job["transcript_json"]:
                return False, "analyzer: transcript_json is empty"
            parsed = json.loads(job["transcript_json"])
            segments = parsed.get("segments", [])
            an = ViralityAnalyzer(api_key=cfg.require_key("gemini"), provider="gemini")
            result = an.analyze_transcript(
                video_title=job["title"] or "Untitled",
                video_duration=float(job["duration_seconds"] or 0.0),
                transcript_segments=segments,
            )
            # Persist candidate clips; the clipper will render them.
            for c in result.clips:
                db.create_clip(
                    job_id=job["id"], account_id=job["account_id"],
                    start_time=c.start_time, end_time=c.end_time,
                    duration_seconds=float(c.end_time) - float(c.start_time),
                    virality_score=float(c.virality_score), hook_text=c.hook_text,
                    title=c.headline, description=c.suggested_caption,
                )
            return True, {"transcript_json": job["transcript_json"]}
        except Exception as exc:
            return False, f"analyzer: {type(exc).__name__}: {exc}"
    return handler


def _make_clipper(cfg: Config, store: AccountStorage, VideoClipper) -> Handler:
    def handler(job, db):
        try:
            raw = job["raw_video_path"]
            if not raw or not Path(raw).exists():
                return False, f"clipper: raw_video_path not found ({raw})"
            clipper = VideoClipper()
            for clip in db.list_clips(job["id"]):
                out = str(store.clip_path(job["account_id"], clip["id"]))
                clipper.cut_clip(
                    raw_video=raw,
                    start_time=float(clip["start_time"]),
                    end_time=float(clip["end_time"]),
                    output_path=out,
                )
                db.update_clip(clip["id"], video_path=out)
            return True, {}
        except Exception as exc:
            return False, f"clipper: {type(exc).__name__}: {exc}"
    return handler


def _make_captioner(cfg: Config, store: AccountStorage, ASSSubtitleGenerator,
                    SubtitleRenderer) -> Handler:
    def handler(job, db):
        try:
            gen = ASSSubtitleGenerator()
            renderer = SubtitleRenderer()
            for clip in db.list_clips(job["id"]):
                if not clip["video_path"]:
                    continue
                words = _words_in_window(job["transcript_json"] or "",
                                         float(clip["start_time"]), float(clip["end_time"]))
                ass = str(store.ass_path(job["account_id"], clip["id"]))
                gen.generate_ass(words=words, output_ass_path=ass)
                final = str(store.clip_path(job["account_id"], clip["id"]).with_suffix(".captioned.mp4"))
                renderer.burn_subtitles(video_path=clip["video_path"], ass_path=ass,
                                        output_path=final)
                db.update_clip(clip["id"], caption_path=ass, video_path=final)
            return True, {}
        except Exception as exc:
            return False, f"captioner: {type(exc).__name__}: {exc}"
    return handler


def _make_metadata(cfg: Config, store: AccountStorage, MetadataCompiler) -> Handler:
    def handler(job, db):
        try:
            compiler = MetadataCompiler(storage_root=str(store.root))
            for clip in db.list_clips(job["id"]):
                if not clip["video_path"]:
                    continue
                hashtags = [h for h in (clip["hashtags"] or "").split() if h]
                compiler.compile(
                    clip_id=clip["id"], video_file=clip["video_path"],
                    caption_file=clip["caption_path"], account_id=job["account_id"],
                    title=clip["title"], description=clip["description"],
                    hashtags=hashtags, hook_text=clip["hook_text"],
                )
            return True, {}
        except Exception as exc:
            return False, f"metadata: {type(exc).__name__}: {exc}"
    return handler


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def register_workers(cfg: Config, db: Optional[Database] = None,
                     storage_root: Optional[str | Path] = None) -> list[str]:
    """Register all available worker stages; returns the stages registered."""
    root = storage_root or (Path(cfg.resolved_db_path).parent.parent / "storage" / "accounts")
    store = AccountStorage(root)

    MediaDownloader = _import("modules.downloader", "MediaDownloader")
    WhisperTranscriber = _import("modules.transcriber", "WhisperTranscriber")
    ViralityAnalyzer = _import("modules.analyzer", "ViralityAnalyzer")
    VideoClipper = _import("modules.clipper", "VideoClipper")
    ASSSubtitleGenerator = _import("modules.captioner", "ASSSubtitleGenerator")
    SubtitleRenderer = _import("modules.captioner", "SubtitleRenderer")
    MetadataCompiler = _import("modules.metadata", "MetadataCompiler")

    registered: list[str] = []
    if MediaDownloader:
        register_handler(DOWNLOADING, _make_downloader(cfg, store, MediaDownloader)); registered.append(DOWNLOADING)
    if WhisperTranscriber:
        register_handler(TRANSCRIBING, _make_transcriber(cfg, store, WhisperTranscriber)); registered.append(TRANSCRIBING)
    if ViralityAnalyzer:
        register_handler(ANALYZING, _make_analyzer(cfg, store, ViralityAnalyzer)); registered.append(ANALYZING)
    if VideoClipper:
        register_handler(CLIPPING, _make_clipper(cfg, store, VideoClipper)); registered.append(CLIPPING)
    if ASSSubtitleGenerator and SubtitleRenderer:
        register_handler(CAPTIONING, _make_captioner(cfg, store, ASSSubtitleGenerator, SubtitleRenderer)); registered.append(CAPTIONING)
    if MetadataCompiler:
        register_handler(METADATA, _make_metadata(cfg, store, MetadataCompiler)); registered.append(METADATA)

    log.info("registered %s worker stage(s): %s", len(registered), ", ".join(registered))
    return registered


__all__ = ["register_workers", "AccountStorage"]