# 🌐 PLAN 06: MULTI-ACCOUNT SCALING ENGINE (N-ACCOUNTS)

> [!ABSTRACT] **Executive Summary**
> Blueprint for scaling the ClipIt System to manage **N independent accounts** (e.g. 1, 5, 20, 50+ channels/clients). Each account operates with isolated input sources, distinct branding/subtitle presets, custom LLM prompt personas, and separated output export queues.

---

## 🎯 Central Hub Connection
- 🎯 **[[PLANS| Back to Central PLANS Node]]**

---

## 🗺️ Multi-Tenant Architecture Diagram

```mermaid
flowchart TD
    classDef hub fill:#831843,stroke:#f43f5e,stroke-width:3px,color:#fff
    classDef acc fill:#4c1d95,stroke:#c084fc,stroke-width:2px,color:#fff
    classDef queue fill:#0e7490,stroke:#38bdf8,stroke-width:2px,color:#fff
    classDef out fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#fff

    SCH[Daemon Scheduler]:::hub --> ACC_ENGINE[N-Account Dispatcher]:::hub

    ACC_ENGINE --> ACC1[Account 01: Tech Shorts]:::acc
    ACC_ENGINE --> ACC2[Account 02: Finance Mindset]:::acc
    ACC_ENGINE --> ACCN[Account N: Custom Client/Niche]:::acc

    ACC1 --> Q1[SQLite Queue (Account 01)]:::queue
    ACC2 --> Q2[SQLite Queue (Account 02)]:::queue
    ACCN --> QN[SQLite Queue (Account N)]:::queue

    Q1 --> OUT1[storage/accounts/acc_01/outputs/]:::out
    Q2 --> OUT2[storage/accounts/acc_02/outputs/]:::out
    QN --> OUTN[storage/accounts/acc_N/outputs/]:::out
```

---

## 🗄️ Database Schemas (`accounts` & `jobs` Link)

```sql
-- N-Account Management Table
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,               -- e.g. 'acc_finance_01'
    name TEXT NOT NULL,                -- e.g. 'Daily Wealth Shorts'
    niche TEXT NOT NULL,               -- e.g. 'Finance & Investing'
    sources_json TEXT NOT NULL,        -- YouTube channels/playlists/folders
    branding_preset_json TEXT NOT NULL,-- Subtitle font, highlight colors, logo overlay
    metadata_preset_json TEXT NOT NULL,-- Prompt tone, hashtag pool, link-in-bio CTA
    max_daily_clips INTEGER DEFAULT 3,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Updated Jobs Table with Foreign Key
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    raw_video_path TEXT,
    audio_path TEXT,
    transcript_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);
```

---

## 🎨 Per-Account Branding & Customization Engine

Each account defines its own visual identity in `branding_preset_json`:

```json
{
  "font_name": "Montserrat ExtraBold",
  "font_size": 64,
  "primary_color": "&H00FFFFFF",
  "highlight_color": "&H0000FFFF",
  "outline_color": "&H00000000",
  "crop_mode": "smart_center_crop",
  "watermark_logo": "storage/accounts/acc_01/watermark.png"
}
```

---

## ⚡ Throughput & Scheduling Rules for N Accounts

> [!IMPORTANT] **1. Round-Robin Queue Allocation**
> The daemon processes jobs using a round-robin schedule across all enabled accounts so no single account starves others of processing time.

> [!TIP] **2. API Rate-Limit & Spacing Protection**
> When managing N accounts, API requests are spaced with configurable delays (e.g. 2–5 seconds between API calls) to prevent hitting OpenAI/Gemini rate limits.

> [!CAUTION] **3. Storage Auto-Cleanup per Account**
> Large raw source videos are automatically deleted after successful clip rendering, retaining only the final generated clips and metadata per account folder to conserve phone storage.

---

## 📂 Multi-Account Directory Hierarchy

```
storage/accounts/
├── acc_01_tech/
│   ├── raw/
│   ├── clips/
│   └── outputs/
│       └── 2026-08-07_clip01_video.mp4
├── acc_02_finance/
...
└── acc_N_custom/
```

---

## 🔗 Plan Connections
- 🎯 **[[PLANS| Central PLANS Hub]]**
- [[00-Master-System-Plan| 🚀 Plan 00: Master System Plan]]
- [[02-SQLite-Queue-State-Machine-Plan| 🗄️ Plan 02: SQLite Queue]]
- [[04-Android-Termux-Daemon-Plan| 📱 Plan 04: Android Daemon]]

#plan/multiaccount #plan/scaling #plan/isolated
