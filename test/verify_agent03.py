"""End-to-end verification for Agent 03 modules (clipper, captioner, metadata)."""
import os, sys, json, subprocess, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.clipper import VideoClipper
from modules.captioner import ASSSubtitleGenerator, SubtitleRenderer
from modules.metadata import MetadataCompiler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "test", "raw_16x9.mp4")
OUT = os.path.join(ROOT, "test", "out")
os.makedirs(OUT, exist_ok=True)

results = []

def probe(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height:format=duration",
        "-of", "json", path])
    d = json.loads(out)
    s = (d.get("streams") or [{}])[0]
    return s.get("width"), s.get("height"), float((d.get("format") or {}).get("duration", 0))

def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + detail if detail else ""))

# 1. Center crop render
try:
    clipper = VideoClipper()
    r = clipper.cut_clip(SRC, 1.0, 11.0, os.path.join(OUT, "clip_center.mp4"), crop_mode="center")
    w, h, dur = probe(r.output_path)
    check("center crop 1080x1920", (w, h) == (1080, 1920), f"{w}x{h} dur={dur:.2f}s cmd_ok={bool(r.ffmpeg_cmd)}")
except Exception:
    check("center crop", False, traceback.format_exc())

# 2. Blur background render
try:
    r2 = clipper.cut_clip(SRC, 2.0, 12.0, os.path.join(OUT, "clip_blur.mp4"), crop_mode="blur")
    w, h, dur = probe(r2.output_path)
    check("blur crop 1080x1920", (w, h) == (1080, 1920), f"{w}x{h} dur={dur:.2f}s")
except Exception:
    check("blur crop", False, traceback.format_exc())

# 3. ASS generation with word highlights
try:
    words = [
        {"word": "This", "start": 0.0, "end": 0.5},
        {"word": "trick", "start": 0.5, "end": 1.0},
        {"word": "changed", "start": 1.0, "end": 1.5},
        {"word": "video", "start": 1.5, "end": 2.0},
        {"word": "editing", "start": 2.0, "end": 2.6},
        {"word": "forever", "start": 2.6, "end": 3.2},
    ]
    gen = ASSSubtitleGenerator()
    ass_path = gen.generate_ass(words, os.path.join(OUT, "cap.ass"))
    content = open(ass_path, encoding="utf-8").read()
    ok = "ScriptType: v4.00+" in content and "Dialogue:" in content and "\\c&H0000FFFF&" in content
    check("ASS generation + highlight tags", ok, f"{len(content)} chars, {content.count('Dialogue:')} lines")
except Exception:
    check("ASS generation", False, traceback.format_exc())

# 4. Burn-in render
try:
    r3 = SubtitleRenderer().burn_subtitles(
        os.path.join(OUT, "clip_center.mp4"), ass_path,
        os.path.join(OUT, "clip_final.mp4"), delete_intermediate=False)
    w, h, dur = probe(r3)
    check("burn-in render 1080x1920", (w, h) == (1080, 1920), f"{w}x{h} dur={dur:.2f}s exists={os.path.exists(r3)}")
except Exception:
    check("burn-in render", False, traceback.format_exc())

# 5. Metadata package
try:
    mc = MetadataCompiler(storage_root=os.path.join(ROOT, "test", "storage"))
    meta = mc.compile(
        clip_id="clip_acc01_001",
        title="Stop Rendering Slowly in FFmpeg 🚀",
        description="Double your export speeds with this setting! #videoediting #ffmpeg",
        hashtags=["ffmpeg", "videoediting", "techhacks", "shorts"],
        cta="Link in bio for full editing guide!",
        account_id="acc_01",
        video_file=os.path.join(OUT, "clip_final.mp4"),
        caption_file=os.path.join(OUT, "cap.ass"),
        hook_text="Did you know AI changed everything?",
    )
    meta_path = os.path.join(ROOT, "test", "storage", "acc_01", "outputs", "metadata.json")
    ok = os.path.exists(meta_path) and meta["title"] == "Stop Rendering Slowly in FFmpeg 🚀"
    ok = ok and meta["hashtags"] == ["#ffmpeg", "#videoediting", "#techhacks", "#shorts"]
    check("metadata.json package", ok, f"hashtags={meta['hashtags']}")
except Exception:
    check("metadata package", False, traceback.format_exc())

# 6. Edge cases
try:
    try:
        clipper.cut_clip(SRC, 1.0, 3.0, os.path.join(OUT, "x.mp4"))  # < 5s
        check("reject <5s clip", False)
    except ValueError as e:
        check("reject <5s clip", "below minimum" in str(e), str(e))
except Exception:
    check("reject <5s clip", False, traceback.format_exc())

try:
    gen2 = ASSSubtitleGenerator()
    gen2.generate_ass([], os.path.join(OUT, "empty.ass"))
    check("reject empty words", False)
except ValueError:
    check("reject empty words", True)

fails = [r for r in results if not r[1]]
print("\n=== SUMMARY: %d/%d passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
