"""
test/e2e_agent03.py - REAL end-to-end vertical short production (TSK-A03-09/10).

Produces an actual 9:16 MP4 from a landscape source:
  1. VideoClipper.cut_clip  -> 1080x1920 vertical clip (center crop, loudnorm)
  2. ASSSubtitleGenerator   -> word-highlight .ass captions (VIRAL_YELLOW)
  3. SubtitleRenderer       -> burn captions in (-c:a copy, zero drift)
  4. MetadataCompiler       -> metadata.json + platform packages
     (post_shorts.json / post_reels.json) for auto-posting

Run:  python test/e2e_agent03.py
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer
from modules.clipper import VideoClipper
from modules.metadata import MetadataCompiler

SRC = os.path.join(ROOT, "test", "raw_16x9.mp4")          # 1920x1080 synthetic source
OUT_DIR = os.path.join(ROOT, "storage", "accounts", "acc_media01", "outputs")
os.makedirs(OUT_DIR, exist_ok=True)

CLIP_ID = "clip_acc_media01_001"
CUT_MP4 = os.path.join(OUT_DIR, f"{CLIP_ID}_cut.mp4")     # intermediate (un-captioned)
FINAL_MP4 = os.path.join(OUT_DIR, f"{CLIP_ID}.mp4")       # final captioned
ASS_PATH = os.path.join(OUT_DIR, f"{CLIP_ID}.ass")

WORDS = [
    {"word": "This",   "start": 0.0,  "end": 0.6},
    {"word": "is",     "start": 0.6,  "end": 1.0},
    {"word": "the",    "start": 1.0,  "end": 1.4},
    {"word": "one",    "start": 1.4,  "end": 1.8},
    {"word": "trick",  "start": 1.8,  "end": 2.6},
    {"word": "that",   "start": 2.6,  "end": 3.0},
    {"word": "changed", "start": 3.0, "end": 4.0},
    {"word": "my",     "start": 4.0,  "end": 4.4},
    {"word": "edits",  "start": 4.4,  "end": 5.2},
    {"word": "forever", "start": 5.2, "end": 6.0},
]

TITLE = "The one editing trick that changed my videos forever"
DESCRIPTION = "Full breakdown + free presets inside. Watch till the end!"
HASHTAGS = ["videoediting", "premierepro", "filmmaking", "editingtips",
            "contentcreator", "tutorial", "verticalvideo"]


def probe(path: str) -> tuple[int, int, float]:
    import subprocess
    import json as _json
    d = _json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_format",
         "-of", "json", path]))
    s = (d.get("streams") or [{}])[0]
    return s.get("width", 0), s.get("height", 0), float((d.get("format") or {}).get("duration", 0))


def main() -> int:
    clipper = VideoClipper()
    captioner = ASSSubtitleGenerator(preset="VIRAL_YELLOW")
    burner = SubtitleRenderer()

    # 1) Cut a real 9:16 vertical clip (center crop + loudnorm).
    res = clipper.cut_clip(
        raw_video=SRC,
        start_time=1.0,
        end_time=8.0,
        output_path=CUT_MP4,
        crop_mode="center",
        encoder="auto",
        audio_loudnorm=True,
        preset="fast",
        crf=20,
    )
    print(f"[1/4] cut clip  -> {res.width}x{res.height}  encoder={res.encoder_used}  "
          f"dur={res.duration:.2f}s  loudnorm={res.audio_normalized}")

    # 2) Generate ASS word-highlight captions.
    captioner.generate_ass(WORDS, ASS_PATH)
    print(f"[2/4] ass file  -> {os.path.basename(ASS_PATH)}  "
          f"(preset={captioner.preset_name}, hl={captioner.highlight})")

    # 3) Burn captions in (audio copied -> zero drift).
    burner.burn_subtitles(CUT_MP4, ASS_PATH, FINAL_MP4, crf=20, delete_intermediate=True)
    print(f"[3/4] burn-in   -> {os.path.basename(FINAL_MP4)}")

    # 4) Package metadata: base + YouTube Shorts + Instagram Reels.
    meta = MetadataCompiler(storage_root=os.path.join(ROOT, "storage", "accounts"))
    pkg = meta.compile_package(
        clip_id=CLIP_ID,
        video_file=FINAL_MP4,
        account_id="acc_media01",
        title=TITLE,
        description=DESCRIPTION,
        hashtags=HASHTAGS,
        cta="Link in bio for the full guide!",
        platform="shorts",
        extra={"caption_file": os.path.basename(ASS_PATH)},
    )
    meta.compile_package(
        clip_id=CLIP_ID,
        video_file=FINAL_MP4,
        account_id="acc_media01",
        title=TITLE,
        # Reels composes the caption from the title when no description is
        # passed (title-led caption body per TSK-A03-10).
        hashtags=HASHTAGS,
        platform="reels",
    )
    print(f"[4/4] metadata  -> metadata.json + post_shorts.json + post_reels.json")

    # ---- verification ---------------------------------------------------
    w, h, dur = probe(FINAL_MP4)
    assert (w, h) == (1080, 1920), f"final clip must be 1080x1920, got {w}x{h}"
    assert dur > 5.0, f"final clip too short: {dur}s"
    assert os.path.exists(FINAL_MP4) and os.path.getsize(FINAL_MP4) > 50_000

    with open(os.path.join(OUT_DIR, "metadata.json"), encoding="utf-8") as f:
        base = json.load(f)
    with open(os.path.join(OUT_DIR, "post_shorts.json"), encoding="utf-8") as f:
        shorts = json.load(f)
    with open(os.path.join(OUT_DIR, "post_reels.json"), encoding="utf-8") as f:
        reels = json.load(f)

    assert all(t.startswith("#") for t in base["hashtags"]), "hashtags must be #-normalized"
    assert "platform" in shorts and shorts["platform"] == "shorts"
    assert "platform" in reels and reels["platform"] == "reels"
    assert shorts["title"] == TITLE[:100]
    assert reels["description"].startswith(TITLE), "reels caption must lead with title"
    assert len(shorts["title"]) <= 100 and len(reels["description"]) <= 2200

    print("\nALL CHECKS PASSED")
    print(f"  final clip : {FINAL_MP4} ({w}x{h}, {dur:.1f}s)")
    print(f"  shorts pkg : {os.path.join(OUT_DIR, 'post_shorts.json')}")
    print(f"  reels pkg  : {os.path.join(OUT_DIR, 'post_reels.json')}")
    print(f"  shorts hashtags: {shorts['hashtag_string']}")
    print(f"  reels caption  : {reels['description'][:120]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
