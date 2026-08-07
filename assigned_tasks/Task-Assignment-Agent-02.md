# 📋 CEO TASK ASSIGNMENT: AGENT 02 (AI INGESTION SPECIALIST)

> [!IMPORTANT] **CEO Directive for Agent 02**
> **Target Files**: modules/watcher.py, modules/downloader.py, modules/transcriber.py, modules/analyzer.py
> **Primary Model**: Gemini 3.6 Flash (Vision + STT - High Effort)
> **Free Fallback**: deepseek-v4-flash-free (200k Context)

---

## 🎯 Central Hub Connections
- 💎 **[[Index| Master Vault Index]]**
- 👑 **[[CEO-Operational-Guide| CEO Orchestrator Guide]]**
- 🤖 **[[Agent-02-AI-Ingestion-Specialist| Agent 02 Hub]]**

---

## 📋 Assigned Tasks Matrix

| Task ID | Task Title | Priority | Status | Target Deliverable |
| :---: | :--- | :---: | :---: | :--- |
| **TSK-A02-01** | Build YouTube RSS Watcher | HIGH | [x] COMPLETED | Parse YouTube RSS XML feeds & enqueue new video IDs |
| **TSK-A02-02** | Build yt-dlp Media Downloader | CRITICAL | [x] COMPLETED | Fetch 1080p MP4 & extract 16kHz mono WAV via FFmpeg |
| **TSK-A02-03** | Integrate Groq Whisper STT API | CRITICAL | [x] COMPLETED | Fetch word-level timestamps (verbose_json) |
| **TSK-A02-04** | Build Gemini Virality Analyzer | CRITICAL | [x] COMPLETED | Prompt LLM for hook/retention scores & Pydantic JSON clip candidates |
| **TSK-A02-05** | Whisper >25MB Audio Splitter | HIGH | [x] COMPLETED | Auto-chunk audio files over 25MB before Groq STT submission |
| **TSK-A02-06** | YouTube Live/Shorts Filter | MEDIUM | [x] COMPLETED | Filter out live streams & validate video aspect ratio |
| **TSK-A02-07** | Gemini Virality Prompt Tuning | HIGH | [x] COMPLETED | Refine hook scoring (0-100) & Pydantic quote extraction |
| **TSK-A02-08** | Exponential Backoff Client | MEDIUM | [x] COMPLETED | Handle API rate-limits with automatic retry backoff |