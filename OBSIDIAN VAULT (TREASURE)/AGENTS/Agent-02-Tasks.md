> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **agy Activation Command (Gemini 3.6 Flash - Primary Vision + STT)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && hermes`
> - **SKILL**: `/ClipIt-AI-Ingestion-Specialist`

# 📋 AGENT 02: TASKS BOARD

- 🤖 **[[Agent-02-AI-Ingestion-Specialist| Back to Agent 02 Hub]]**

## 📌 Active Tasks
- [x] Build YouTube RSS channel watcher (`modules/watcher.py`)
- [x] Build `yt-dlp` video downloader & audio extractor (`modules/downloader.py`)
- [x] Build Groq Whisper API STT client (`modules/transcriber.py`)
- [x] Construct Gemini 1.5 Flash virality prompt engine (`modules/analyzer.py`)
- [x] Whisper >25MB Audio Splitter (`modules/transcriber.py`)
- [x] YouTube Live/Shorts Filter (`modules/watcher.py` & `modules/downloader.py`)
- [x] Gemini Virality Prompt Tuning & Quote Extraction (`modules/analyzer.py`)
- [x] Exponential Backoff Client (`modules/transcriber.py` & `modules/analyzer.py`)



### 👁️ Multimodal Vision Capability (SECONDARY)
- **Model**: Gemini 1.5 Flash Vision / GPT-4o Vision
- **Vision Tasks**:
  1. **Visual Hook Analysis**: Analyze sampled keyframe images (1 frame every 3s) alongside audio transcripts to detect visual hooks (slide reveals, facial expressions, chart highlights).
  2. **Multi-Modal Virality Scoring**: Combine audio transcript score (0-10) with visual motion density score (0-10).



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: GPT-4o / Opencode Zen (-free)