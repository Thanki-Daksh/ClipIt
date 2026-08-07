# ✂️ ClipIt — Overview & Product Specifications

> [!NOTE] 🌟 **Core Product Vision**
> **ClipIt** is an autonomous, open-source, self-hosted AI clipping engine designed to turn long-form videos (YouTube, podcasts, streams) into high-retention vertical clips (TikTok, Shorts, Reels) autonomously across **N social media accounts**.

---

## 🔄 End-to-End ClipIt Pipeline

```mermaid
flowchart TD
    classDef input fill:#1e1b4b,stroke:#6366f1,stroke-width:2px,color:#fff
    classDef cloud fill:#4c1d95,stroke:#c084fc,stroke-width:2px,color:#fff
    classDef local fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#fff
    classDef out fill:#78350f,stroke:#fbbf24,stroke-width:2px,color:#fff

    IN1[📺 YouTube Channel RSS]:::input --> WATCH[1. ClipIt Watcher]:::local
    IN2[📁 Local Watch Folder]:::input --> WATCH
    WATCH --> DOWN[2. Downloader yt-dlp]:::local
    DOWN --> TRANS[3. Transcriber Whisper API]:::cloud
    TRANS --> ANALYZ[4. Analyzer LLM Hook Scoring]:::cloud
    ANALYZ --> CLIP[5. Clipper FFmpeg 9:16 Vertical]:::local
    CLIP --> CAPT[6. Captioner ASS Subtitles]:::local
    CAPT --> META[7. Metadata Generator LLM]:::cloud
    META --> QUEUE[8. N-Account Review Queue]:::out
```

---

## 🛡️ ClipIt Guarantees

> [!SUCCESS] **1. Crash & Reboot Resilience**
> Jobs strictly advance through SQLite states (`PENDING` ➔ `DOWNLOADING` ➔ `TRANSCRIBING` ➔ `ANALYZING` ➔ `CLIPPING` ➔ `CAPTIONING` ➔ `METADATA` ➔ `COMPLETED`). If the phone restarts, background execution resumes from the exact state without duplicating completed work.

> [!TIP] **2. Unlimited Multi-Account Scaling (N Accounts)**
> ClipIt handles 1 to 50+ accounts seamlessly with isolated branding presets, custom LLM prompt tones, and distinct output export queues.

> [!IMPORTANT] **3. Strictly Decoupled Architecture**
> Every module implements `process(job_context)` independently. Speech-to-text engines, LLMs, or video filters can be swapped with zero impact on the rest of the system.

---

## 🔗 Related References
- [[Pipeline-Modules| 🧩 Detailed Module Specs]]
- [[Decisions#ADR-001| ⚖️ ADR-001: Hybrid Cloud AI + Local FFmpeg Strategy]]
- [[Decisions#ADR-002| ⚖️ ADR-002: SQLite Job Queue & State Machine]]
- [[Tasks| 📝 Master Task Board]]
