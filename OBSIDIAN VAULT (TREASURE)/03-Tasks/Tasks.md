# 📋 MASTER SYSTEM TASK BACKLOG — CLIPIT

- 💎 **[[Index| Master Vault Index]]**
- 🤖 **[[AGENTS| Master AGENTS Hub]]**
- 🎯 **[[PLANS| Master PLANS Hub]]**

---

## 📌 Implementation Sprint Tasks

### Phase 1: Core Database & Queue State Machine
- [x] Design SQLite Schema (`accounts`, `jobs`, `clips`, `logs`)
- [ ] Implement `core/db.py` SQLite connection & WAL mode
- [ ] Implement `core/queue.py` state machine manager
- [ ] Build crash recovery auto-resume mechanism

### Phase 2: Ingestion & AI Intelligence Pipeline
- [ ] Build YouTube RSS channel watcher (`modules/watcher.py`)
- [ ] Build `yt-dlp` video downloader & audio extractor (`modules/downloader.py`)
- [ ] Integrate Groq Whisper API STT client (`modules/transcriber.py`)
- [ ] Construct Gemini 1.5 Flash virality prompt engine (`modules/analyzer.py`)

### Phase 3: FFmpeg Crop & Subtitle Burn-In
- [ ] Implement FFmpeg 9:16 vertical video crop engine (`modules/clipper.py`)
- [ ] Build ASS animated subtitle generator (`modules/captioner.py`)
- [ ] Implement subtitle burn-in FFmpeg filter
- [ ] Build metadata compiler (`modules/metadata.py`)

### Phase 4: Local Web Review UI
- [ ] Build FastAPI localhost web server (`ui/app.py`)
- [ ] Build mobile dark-mode HTML template (`ui/templates/index.html`)
- [ ] Build 9:16 HTML5 video preview card & modal editor (`ui/static/js/app.js`)
- [ ] Implement 1-tap clip approval REST API (`/api/clips/{id}/approve`)

### Phase 5: Android Background Daemon & Safety
- [ ] Build Termux daemon launcher (`scripts/start.sh`) with wake-lock acquisition
- [ ] Build clean shutdown script (`scripts/stop.sh`) with wake-lock release
- [ ] Build battery & thermal monitor (`scripts/termux_monitor.py`)
- [ ] Build Android boot auto-start helper script (`scripts/boot_recovery.sh`)

### Phase 6: Automated Testing & Security
- [ ] Build shared test fixtures (`tests/conftest.py`)
- [ ] Build state machine & crash recovery test suite (`tests/test_queue.py`)
- [ ] Build FFmpeg 9:16 crop `ffprobe` verification test (`tests/test_clipper.py`)
