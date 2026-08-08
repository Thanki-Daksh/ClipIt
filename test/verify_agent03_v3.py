"""verify_agent03_v3.py - Verification for Agent 03 tasks TSK-A03-08..15.

Covers (with REAL renders where stated):
  TSK-A03-08  Dynamic watermark overlay (bottom-right) - MD5-diffed vs plain
  TSK-A03-09  loudnorm default target -14 LUFS (mobile-speaker spec)
  TSK-A03-10  High-res thumbnail generator (1080x1920 poster PNG)
  TSK-A03-11  ASS font fallback engine (Montserrat/Inter/Arial)
  TSK-A03-12  minterpolate 60fps motion-blur doubler (blend mode, fast check)
  TSK-A03-13  auto color-grading presets (vivid/punch/cinematic/warm)
  TSK-A03-14  aspect-ratio auto-pad (9:16 without stretching)
  TSK-A03-15  120s FFmpeg timeout guard (functional 1s-timeout kill test)

Run:  python test/verify_agent03_v3.py
"""
from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.captioner import ASS_PRESETS, ASSSubtitleGenerator, SubtitleRenderer
from modules.clipper import (
    COLOR_PRESETS,
    LOUDNESS_I,
    RENDER_TIMEOUT,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    VideoClipper,
)

SRC = os.path.join(ROOT, "test", "raw_16x9.mp4")
OUT = os.path.join(ROOT, "test", "out3")
os.makedirs(OUT, exist_ok=True)

results = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok)))
    mark = "PASS" if ok else "FAIL"
    print(f"{mark} - {name}" + (f" | {detail}" if detail else ""))


def ffprobe_dims(path: str):
    import json
    d = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate", "-show_format",
         "-of", "json", path]))
    s = (d.get("streams") or [{}])[0]
    n, dd = map(int, s["avg_frame_rate"].split("/")) if s.get("avg_frame_rate") else (0, 1)
    fps = n / dd if dd else 0.0
    return s.get("width", 0), s.get("height", 0), fps


def md5_crop(path: str, crop: str, at: float = 0.3) -> str:
    out = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{at:.2f}", "-i", path,
         "-vf", crop, "-frames:v", "1", "-f", "md5", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.decode().strip()
    return out.split("=", 1)[-1]


def loudness_i(path: str) -> float:
    out = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "ebur128", "-f", "null", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stderr.decode("utf-8", "replace")
    lines = out.splitlines()
    for i in range(len(lines)):
        if "Integrated loudness" in lines[i]:
            for j in range(i, min(i + 5, len(lines))):
                toks = lines[j].split()
                for k, t in enumerate(toks):
                    if t == "I:" and k + 1 < len(toks):
                        try:
                            return float(toks[k + 1].rstrip("LUFS"))
                        except ValueError:
                            continue
    return float("nan")


def make_logo() -> str:
    """Solid red 200x200 PNG as the channel logo."""
    logo = os.path.join(OUT, "logo.png")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=200x200",
         "-frames:v", "1", logo],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    return logo


# ---- TSK-A03-11: font fallback engine ---------------------------------------
avail = ASSSubtitleGenerator.available_fonts()
resolved = ASSSubtitleGenerator.resolve_font("Montserrat ExtraBold")
check("font fallback resolves to installed family",
      resolved in ("Montserrat ExtraBold", "Montserrat", "Inter", "Arial"),
      f"resolved={resolved}, host fonts={len(avail)} files")
check("font never returns an unknown family",
      resolved != "Montserrat ExtraBold" or "montserrat" in " ".join(avail),
      f"avail sample: {sorted(avail)[:3]}")
check("spec-era preset aliases exist",
      {"TIKTOK_YELLOW", "CLEAN_WHITE"} <= set(ASS_PRESETS),
      f"presets={sorted(ASS_PRESETS)}")
gen = ASSSubtitleGenerator(preset="TIKTOK_YELLOW")
check("alias preset resolves palette",
      gen.highlight == "&H0000FFFF", f"hl={gen.highlight} font={gen.font_name}")

# ---- TSK-A03-13/14/12: combined pad + grade + 60fps real render ----------
clipper = VideoClipper()
mixed = os.path.join(OUT, "clip_pad_grade_60.mp4")
r = clipper.cut_clip(SRC, 1.0, 7.0, mixed, crop_mode="pad",
                     encoder="libx264", color_grade="vivid",
                     smooth_60fps=True, minterpolate_mode="blend")
w, h, fps = ffprobe_dims(mixed)
cmd_str = " ".join(r.ffmpeg_cmd)
check("pad mode renders 1080x1920", (w, h) == (TARGET_WIDTH, TARGET_HEIGHT), f"{w}x{h}")
check("auto-pad filter in command", "pad=1080:1920" in cmd_str, "pad=...")
check("color grading 'vivid' in chain", "eq=contrast=1.12:saturation=1.28" in cmd_str)
check("minterpolate 60fps doubler in chain", "minterpolate=fps=60" in cmd_str)
check("60fps output frame rate", 55.0 <= fps <= 61.0, f"fps={fps:.2f}")
try:
    clipper.cut_clip(SRC, 1.0, 7.0, os.path.join(OUT, "bad.mp4"),
                     color_grade="nope", encoder="libx264")
    check("unknown grade rejected", False, "no ValueError raised")
except ValueError:
    check("unknown grade rejected", True, "ValueError raised")

# ---- TSK-A03-09: loudnorm default target = -14 LUFS -----------------------
plain = os.path.join(OUT, "clip_plain.mp4")
r2 = clipper.cut_clip(SRC, 1.0, 7.0, plain,
                      encoder="libx264", audio_loudnorm=True)
I = loudness_i(plain)
check("default loudnorm target -14 LUFS",
      r2.audio_normalized and abs(I - LOUDNESS_I) < 0.8, f"I={I:.1f} LUFS (spec -14)")

# ---- TSK-A03-08: watermark overlay, real render ---------------------------
logo = make_logo()
wm = os.path.join(OUT, "clip_wm.mp4")
r3 = clipper.cut_clip(SRC, 1.0, 7.0, wm, encoder="libx264",
                      watermark_path=logo, watermark_scale=0.12)
ww, wh, _ = ffprobe_dims(wm)
check("watermark render 1080x1920", (ww, wh) == (TARGET_WIDTH, TARGET_HEIGHT), f"{ww}x{wh}")
cr_plain = md5_crop(plain, "crop=260:260:760:1600")   # bottom-right region
cr_wm = md5_crop(wm, "crop=260:260:760:1600")
check("watermark burned bottom-right (pixel diff)",
      cr_plain != cr_wm, f"md5 {cr_plain[:8]} vs {cr_wm[:8]}")
logo_cmd = " ".join(r3.ffmpeg_cmd)
check("watermark overlay filter in chain", "overlay=main_w-overlay_w-36" in logo_cmd)

# ---- TSK-A03-10: thumbnail -------------------------------------------------
th = os.path.join(OUT, "poster.png")
clipper.extract_thumbnail(video_path=wm, output_png=th, at_time=0.5)
tw, thh, _ = ffprobe_dims(th)
check("thumbnail 1080x1920 PNG",
      os.path.exists(th) and (tw, thh) == (TARGET_WIDTH, TARGET_HEIGHT) and th.endswith(".png"),
      f"{tw}x{thh}")

# ---- TSK-A03-15: timeout guard ---------------------------------------------
check("RENDER_TIMEOUT constant = 120", RENDER_TIMEOUT == 120, f"{RENDER_TIMEOUT}s")
try:
    VideoClipper(timeout=1).cut_clip(
        SRC, 1.0, 7.0, os.path.join(OUT, "never.mp4"),
        crop_mode="blur", smooth_60fps=True, minterpolate_mode="blend",
        encoder="libx264",
    )
    check("timeout guard fires on slow render", False, "no timeout raised")
except RuntimeError as e:
    check("timeout guard fires on slow render",
          "timed out" in str(e).lower() or "timeout" in str(e).lower(),
          str(e)[:80])
check("burn-in renderer has timeout guard", SubtitleRenderer().timeout == 120,
      f"timeout={SubtitleRenderer().timeout}")

fails = [x for x in results if not x[1]]
print("\n=== SUMMARY: %d/%d passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)