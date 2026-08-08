> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/tests`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/tests" && clear && agy`
> - **SKILL**: `/ClipIt-QA-Security-Auditor`

# 📋 AGENT 06: TASKS BOARD

- 🧪 **[[Agent-06-QA-Security-Auditor| Back to Agent 06 Hub]]**

## 📌 Active Tasks
- [x] Build shared test fixtures (`tests/conftest.py`)
- [x] Build state machine & crash recovery test suite (`tests/test_queue.py`)
- [x] Build FFmpeg 9:16 crop `ffprobe` verification test (`tests/test_clipper.py`)
- [x] Build API key security & sanitization scanner
- [x] TSK-A06-05: Full E2E pipeline test (`tests/test_e2e.py`) — enqueue ➔ real .mp4 render
- [x] TSK-A06-06: Black-frame & silence probe (`tests/media_qa.py` + `tests/test_media_qa.py`)
- [x] TSK-A06-07: Codebase secret sanitizer (`tests/secret_sanitizer.py` + `tests/test_security.py`)
- [x] TSK-A06-08: Queue concurrency stress (`tests/test_concurrency.py`) — 50-thread burst
- [x] TSK-A06-09: Live video pipeline & auto-poster tests (`tests/test_live_pipeline.py`, `tests/test_subtitle_render.py`, `tests/test_auto_publisher.py`) — real intake→render→publish contract



### 👁️ Multimodal Vision Capability (QA AUDIT)
- **Model**: Automated Keyframe FFmpeg Extractor & Vision Prober
- **Vision Tasks**:
  1. **Visual QA Pass/Fail Probing**: Extract 3 keyframes (beginning, middle, end) of rendered .mp4 clips and verify resolution (1080x1920) and non-black frame output.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet