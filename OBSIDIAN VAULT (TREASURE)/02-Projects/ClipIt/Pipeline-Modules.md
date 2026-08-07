# ⚙️ PIPELINE MODULES ARCHITECTURE & CONTRACTS

- 💎 **[[Index| Master Vault Index]]**
- 🤖 **[[AGENTS| Master AGENTS Hub]]**
- 🎯 **[[PLANS| Master PLANS Hub]]**
- 🚀 **[[Overview| Project Overview]]**

---

## 🛠️ Pipeline Modules Overview

1. **`modules/watcher.py`** — YouTube RSS Feed & Channel Poller
2. **`modules/downloader.py`** — `yt-dlp` Video Fetcher & `.wav` Audio Extractor
3. **`modules/transcriber.py`** — Groq Whisper STT Word-Level Timestamp Client
4. **`modules/analyzer.py`** — Gemini 1.5 Flash LLM Virality Scoring Engine
5. **`modules/clipper.py`** — FFmpeg 9:16 Vertical Video Center & Stacked Crop Engine
6. **`modules/captioner.py`** — ASS Subtitle & Word Highlight Generator
7. **`modules/metadata.py`** — Social Media Title, Description, & Hashtag Compiler
