# 📋 CEO TASK ASSIGNMENT: AGENT 03 (MEDIA GRAPHICS ENGINEER)

> [!IMPORTANT] **CEO Directive for Agent 03**
> **Target Files**: modules/clipper.py, modules/captioner.py, modules/metadata.py
> **Primary Model**: Gemini 3.6 Flash (High Effort)
> **Free Fallback**: deepseek-v4-flash-free (200k Context)

---

## 🎯 Central Hub Connections
- 💎 **[[Index| Master Vault Index]]**
- 👑 **[[CEO-Operational-Guide| CEO Orchestrator Guide]]**
- 🎬 **[[Agent-03-Media-Graphics-Engineer| Agent 03 Hub]]**

---

## 📋 Assigned Tasks Matrix

| Task ID | Task Title | Priority | Status | Target Deliverable |
| :---: | :--- | :---: | :---: | :--- |
|| **TSK-A03-01** | Build FFmpeg 9:16 Crop Engine | CRITICAL | [x] COMPLETED | Center crop & stacked blurred background render modes verified (1080x1920) |
|| **TSK-A03-02** | Build ASS Subtitle Generator | CRITICAL | [x] COMPLETED | ASS header + word-by-word active BGR highlight colors encoded & verified |
|| **TSK-A03-03** | Build Subtitle Burn-In Pipeline | HIGH | [x] COMPLETED | FFmpeg subtitle burn-in via `subtitles=` filter w/ `-c:a copy` (zero drift) |
|| **TSK-A03-04** | Build Metadata Package Compiler | MEDIUM | [x] COMPLETED | metadata.json written alongside .mp4 in account outputs/ verified |
|| **TSK-A03-05** | 3 ASS Subtitle Style Presets | HIGH | [x] COMPLETED | VIRAL_YELLOW / MINIMAL_WHITE / NEON_CYAN presets verified |
|| **TSK-A03-06** | Dual-Pass Render Engine | HIGH | [x] COMPLETED | h264_nvenc w/ functional driver probe + automatic libx264 fallback |
|| **TSK-A03-07** | Speaker Face Auto-Crop Math | HIGH | [x] COMPLETED | Dynamic 9:16 window centered on face bbox, clamped + even-safe |
|| **TSK-A03-08** | Audio Loudness Normalizer | MEDIUM | [x] COMPLETED | FFmpeg loudnorm I=-16 TP=-1.5 LRA=11 verified -16.0 LUFS |
|| **TSK-A03-09** | Real FFmpeg 9:16 Crop & ASS Subtitle Burn-In | CRITICAL | [x] COMPLETED | `test/e2e_agent03.py` renders real 1080x1920 MP4 + burns word-highlight ASS; caption strip pixel-diff verified |
|| **TSK-A03-10** | Shorts & Reels Metadata & Hash Packaging | HIGH | [x] COMPLETED | `format_for_platform`/`compile_package` emit post_shorts.json + post_reels.json w/ title caps & #-normalized tags |
