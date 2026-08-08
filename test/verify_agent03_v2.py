"""End-to-end verification for Agent 03 tasks TSK-A03-05..08 (presets, nvenc fallback, face crop, loudnorm)."""
import os
import sys
import json
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.clipper import VideoClipper, TARGET_WIDTH, TARGET_HEIGHT
from modules.captioner import ASSSubtitleGenerator, ASS_PRESETS

OUT = os.path.join(ROOT, "test", "out2")
os.makedirs(OUT, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(("PASS" if ok else "FAIL"), "-", name, ("| " + detail if detail else ""))


def video_dims(path):
    d = json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", path]))
    s = (d.get("streams") or [{}])[0]
    return s.get("width"), s.get("height")


def loudness_i(path):
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
                        return float(toks[k + 1].rstrip("LUFS"))
    return None


# ---- TSK-A03-05: presets --------------------------------------------------
for p in ["VIRAL_YELLOW", "MINIMAL_WHITE", "NEON_CYAN"]:
    gen = ASSSubtitleGenerator(preset=p)
    words = [{"word": "This", "start": 0, "end": 0.5}, {"word": "trick", "start": 0.5, "end": 1.0},
             {"word": "changed", "start": 1.0, "end": 1.5}, {"word": "everything", "start": 1.5, "end": 2.0}]
    out = gen.generate_ass(words, os.path.join(OUT, f"cap_{p}.ass"))
    s = open(out, encoding="utf-8").read()
    ok = ("ScriptType: v4.00+" in s and gen.highlight in s and "Dialogue:" in s and gen.font_name in s)
    check(f"preset {p}", ok, f"hl={gen.highlight} font={gen.font_name} size={gen.font_size}")
try:
    ASSSubtitleGenerator(preset="BOGUS")
    check("reject unknown preset", False)
except ValueError:
    check("reject unknown preset", True)
check("presets exported", list(ASS_PRESETS) == ["VIRAL_YELLOW", "TIKTOK_YELLOW", "MINIMAL_WHITE", "CLEAN_WHITE", "NEON_CYAN"])

# ---- TSK-A03-06: dual-pass render engine -----------------------------------
V = os.path.join(ROOT, "test", "raw_16x9.mp4")
clipper = VideoClipper()
src_w, src_h, _ = clipper._probe(V)
check("source dims", (src_w, src_h) == (1920, 1080), f"{src_w}x{src_h}")
nvenc_avail = clipper._detect_nvenc()
check("nvenc functional probe", nvenc_avail is False, "host lacks nvcuda.dll -> must fall back")
check("auto candidates libx264-only on this host", clipper._encoder_candidates("auto") == ["libx264"], str(clipper._encoder_candidates("auto")))
# On a host WITH the NVIDIA driver, auto would be gpu-first; here we force libx264.
check("force libx264 -> single candidate", clipper._encoder_candidates("libx264") == ["libx264"])

r = clipper.cut_clip(V, 1.0, 11.0, os.path.join(OUT, "clip_libx264.mp4"),
                     crop_mode="center", encoder="libx264")
w, h = video_dims(r.output_path)
check("libx264 render", (w, h) == (TARGET_WIDTH, TARGET_HEIGHT), f"{w}x{h} enc={r.encoder_used}")

# ---- TSK-A03-07: face auto-crop math ---------------------------------------
fw = clipper.face_crop_window((800, 540, 200, 200), 1920, 1080)
center_ok = (fw.x + fw.w // 2) == 900
check("face crop centers on face x", center_ok, str(fw))
ratio = fw.w / fw.h
check("face crop aspect ~9/16", abs(ratio - 9 / 16) < 0.01, f"w/h={ratio:.4f}")
check("face crop even + in bounds",
      fw.w % 2 == 0 and fw.h % 2 == 0 and 0 <= fw.x <= 1920 - fw.w and 0 <= fw.y <= 1080 - fw.h, str(fw))
fw2 = clipper.face_crop_window((0, 500, 50, 50), 1920, 1080)
check("face crop clamps left edge", fw2.x == 0, f"{fw2}")

# ---- TSK-A03-09: loudnorm (-14 LUFS mobile-speaker spec) ----------------
r_n = clipper.cut_clip(V, 1.0, 8.0, os.path.join(OUT, "clip_norm.mp4"),
                       encoder="libx264", audio_loudnorm=True,
                       loudness_i=-14.0, loudness_tp=-1.5, loudness_lra=11.0)
I = loudness_i(r_n.output_path)
check("loudnorm applied", r_n.audio_normalized and I is not None and abs(I - (-14.0)) < 0.8, f"I={I} LUFS")

# ---- combined: face crop + loudnorm + auto encoder ----------------------------
r2 = clipper.cut_clip(V, 2.0, 9.0, os.path.join(OUT, "clip_face_norm.mp4"),
                      face_bbox=(900, 540, 200, 200), encoder="auto", audio_loudnorm=True)
w, h = video_dims(r2.output_path)
ok = (w, h) == (TARGET_WIDTH, TARGET_HEIGHT) and r2.crop_window is not None and r2.audio_normalized
check("combined face+loudnorm", ok, f"{w}x{h} crop={r2.crop_window} enc={r2.encoder_used}")

fails = [x for x in results if not x[1]]
print("\n=== SUMMARY: %d/%d passed ===" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)