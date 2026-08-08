> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-Media-Graphics-Engineer`

# 📋 AGENT 03: TASKS BOARD

- 🎬 **[[Agent-03-Media-Graphics-Engineer| Back to Agent 03 Hub]]**

## 📌 Active Tasks
- [x] Implement FFmpeg 9:16 vertical video crop engine (`modules/clipper.py`) — VERIFIED 1080x1920
- [x] Build ASS animated subtitle generator (`modules/captioner.py`) — VERIFIED word-highlight tags
- [x] Implement subtitle burn-in FFmpeg filter — VERIFIED `-c:a copy` zero-drift
- [x] Build metadata compiler (`modules/metadata.py`) — VERIFIED metadata.json beside .mp4
- [x] Add 3 ASS style presets (VIRAL_YELLOW / MINIMAL_WHITE / NEON_CYAN) — VERIFIED
- [x] Dual-pass render engine (h264_nvenc + libx264 fallback) — VERIFIED functional probe
- [x] Speaker face auto-crop math — VERIFIED face-centered 9:16 window
- [x] Audio loudness normalizer (loudnorm) — VERIFIED -14.0 LUFS output (mobile-speaker spec)
- [x] Real FFmpeg 9:16 crop + ASS subtitle burn-in — VERIFIED `test/e2e_agent03.py` ALL CHECKS PASSED
- [x] Shorts & Reels metadata + hashtag packaging — VERIFIED post_shorts.json + post_reels.json
- [x] Dynamic watermark & overlay generator — VERIFIED bottom-right pixel diff (TSK-A03-08)
- [x] High-res thumbnail generator — VERIFIED 1080x1920 poster PNG (TSK-A03-10)
- [x] ASS font fallback engine — VERIFIED Montserrat/Inter/Arial auto-resolve (TSK-A03-11)
- [x] Motion blur & 60fps doubler (minterpolate) — VERIFIED fps=60 output (TSK-A03-12)
- [x] Auto color-grading presets — VERIFIED vivid/punch/cinematic/warm (TSK-A03-13)
- [x] Aspect-ratio auto-pad — VERIFIED 1080x1920 without stretching (TSK-A03-14)
- [x] FFmpeg 120s timeout guard — VERIFIED functional kill + burn-in guard (TSK-A03-15)



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