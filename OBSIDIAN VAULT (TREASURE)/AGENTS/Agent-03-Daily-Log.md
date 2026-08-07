> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-Media-Graphics-Engineer`

# 📅 AGENT 03: DAILY ACTIVITY LOG

- 🎬 **[[Agent-03-Media-Graphics-Engineer| Back to Agent 03 Hub]]**

## 2026-08-07
- Defined FFmpeg crop filters for center 9:16 crop and blurred background padding.
- Created ASS subtitle header template with Montserrat ExtraBold font spec.
- **BUILT `modules/clipper.py`** — `VideoClipper.cut_clip()` with `center` (smart center-crop) and `blur` (stacked blurred-background) modes. Enforces <5s clip rejection, 500MB disk check, `-avoid_negative_ts make_zero`, and ffprobe verification of 1080x1920.
- **BUILT `modules/captioner.py`** — `ASSSubtitleGenerator.generate_ass()` writes v4.00+ header with Montserrat ExtraBold + word-by-word active BGR highlight (`{\c&H0000FFFF&}`). `SubtitleRenderer.burn_subtitles()` burns via FFmpeg `subtitles=` filter with `-c:a copy` (zero audio drift). Fix: cd into subtitle dir + basename to dodge Windows drive-colon filter-arg issue.
- **BUILT `modules/metadata.py`** — `MetadataCompiler.compile()` merges title/description/hashtags/CTA/hook into metadata.json beside the final .mp4 in `storage/accounts/{account_id}/outputs/`.
- **TESTS**: `python test/verify_agent03.py` => **7/7 PASS** (both crop modes render exactly 1080x1920; ASS highlight tags present; burn-in renders 1080x1920 with audible-audio copied; metadata.json hashtag normalization verified; rejects <5s clip and empty words). Burn-in confirmed via differing bottom-frame MD5 between captioned vs raw clip. Existing suite `pytest tests/` => **35 passed**.
- **TSK-A03-05 PRESETS**: Added `ASS_PRESETS` (VIRAL_YELLOW, MINIMAL_WHITE, NEON_CYAN) to `modules/captioner.py`. `ASSSubtitleGenerator(preset=...)` now resolves palette (primary/highlight/outline/back/font/size); header emits spec-exact `{\c&HBBGGRR&}` inline highlight.
- **TSK-A03-06 DUAL-PASS**: `VideoClipper.cut_clip(encoder="auto")` now offers h264_nvenc first then automatic libx264 fallback. `_detect_nvenc()` performs a **functional** 1-frame nvenc encode probe (not just encoder listing) so a missing `nvcuda.dll` correctly resolves to libx264 instead of hanging. Fixed `-map 0:a?` dropping video; blur uses `-filter_complex`.
- **TSK-A03-07 FACE CROP]: `VideoClipper.face_crop_window(bbox, src_w, src_h)` computes the largest 9:16 window centered on the face with even-safe dims, clamped to source bounds; wired into `cut_clip(face_bbox=...)` which probes source dims first. Verified window centers exactly on face x; left-edge clamp works.
- **TSK-A03-08 LOUDNORM**: `cut_clip(audio_loudnorm=True)` applies `loudnorm=I=-16:TP=-1.5:LRA=11`. Verified source -21.8 LUFS -> **-16.0 LUFS** output (re-encodes AAC).
- **VERIFICATION v2**: `test/verify_agent03_v2.py` => **16/16 PASS**. `pytest tests/` => **78 passed** (full suite; Agent 06's new clipper/pipeline/e2e/healt/media_qa/queue tests included).
- **TSK-A03-09 REAL CROP+BURN E2E**: Added `test/e2e_agent03.py` — produces a REAL 1080x1920 vertical MP4 from a 1920x1080 source: `VideoClipper.cut_clip` (center+libx264+loudnorm) -> `ASSSubtitleGenerator` (VIRAL_YELLOW) -> `SubtitleRenderer.burn_subtitles` (-c:a copy) -> `MetadataCompiler.compile_package`. ALL CHECKS PASSED; caption strip pixel-diff = 292,946/324,000 changed pixels (word highlight truly burned). Full pytest run: **73/78** (5 new failures are all in Agent 06's UNCOMMITTED test files: test_auto_publisher, test_live_pipeline, test_oauth_credentials, test_persistence, test_security — not my modules).
- **TSK-A03-10 SHORTS/REELS PACKAGING**: Extended `modules/metadata.py` with `PLATFORM_LIMITS`, `format_for_platform()` and `compile_package()`. Writes `post_shorts.json` (forces #shorts, 100-char title cap) and `post_reels.json` (title-led caption body, 2,200-char cap). Both verified via `test/e2e_agent03.py` => metadata.json + post_shorts.json + post_reels.json produced in `storage/accounts/acc_media01/outputs/`.



### 👁️ Multimodal Vision Capability (PRIMARY)
- **Model**: Gemini 1.5 Flash Vision / OpenCV Frame Analyzer
- **Vision Tasks**:
  1. **Smart Speaker Face Tracking**: Inspect keyframes to detect speaker face coordinates for dynamic 9:16 center cropping.
  2. **Subtitle Placement Audit**: Verify ASS animated captions do not obscure speaker faces or lower-third graphics.
  3. **Render Artifact Detection**: Visually audit exported video keyframes for black bars, distortion, or color corruption.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet