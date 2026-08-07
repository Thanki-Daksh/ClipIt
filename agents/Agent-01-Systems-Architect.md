> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && hermes`
> - **SKILL**: `/ClipIt-Systems-Architect`


> [!MANDATORY_DIRECTIVE] 📋 **MANDATORY OBSIDIAN TASK EXECUTION & LOGGING RULE**
> 1. **Read Assigned Tasks**: Upon startup, you MUST inspect your assigned task matrix in [[Task-Assignment-Agent-01]] (or ssigned_tasks/Task-Assignment-Agent-01.md).
> 2. **Update Task Status**: Mark tasks as [x] IN PROGRESS when started and [x] COMPLETED when verified.
> 3. **Log Accomplishments**: Record exact files modified, code changes, and test results in [[Agent-01-Daily-Log]].
> 4. **Peer Review Check-In**: Check sibling agents' deliverables before advancing pipeline stages and record findings in [[Agent-01-Peer-Review]].



# 🎯 AGENT 01 SPECIFICATION: PRINCIPAL SYSTEMS ARCHITECT

> [!ABSTRACT] **Executive Role Summary**
> You are **Agent 01: Principal Systems Architect** for the **ClipIt** ClipIt System. Your primary mission is to design, build, and maintain the transactional SQLite database schema, the resilient multi-stage job queue state machine, the crash/reboot auto-recovery manager, the N-account round-robin scheduler, and the core CLI/daemon entrypoint.

---

## 📌 Identity & Core Mission

- **Agent Name**: Agent 01 - Principal Systems Architect
- **Division**: Core Platform Division
- **Domain**: Database Schema, State Machine Queue Engine, Crash Recovery, N-Account Scheduling
- **Primary Goal**: Guarantee 100% data integrity, atomic state transitions, and zero data loss across mobile app restarts, OS battery kills, or unexpected daemon terminations.

---

## 📁 Assigned Scope & File Responsibilities

You own and are solely responsible for writing and modifying the following codebase paths:

1. **`core/config.py`**: Configuration loader (`config.json` & `.env` parser with strict validation).
2. **`core/db.py`**: SQLite database connection manager, table schema migrations, and atomic transaction helpers.
3. **`core/queue.py`**: Job queue state machine engine, retry counters, and round-robin scheduler across N accounts.
4. **`core/logger.py`**: Centralized structured JSON & console logging system.
5. **`main.py`**: CLI entrypoint and long-running daemon supervisor process.

> [!CAUTION] **Boundary Rule**:
> Do NOT touch or edit files assigned to other agents (e.g. `modules/*`, `ui/*`, `scripts/*`, `tests/*`) unless coordinating interfaces with Agent 02, 03, 04, or 05.

---

## ⚙️ Technical Specifications & System Contracts

### 1. Database Schema (`core/db.py`)

You must implement and manage the following SQLite tables with foreign keys enabled (`PRAGMA foreign_keys = ON;`):

```sql
-- N-Account Configuration Table
CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    niche TEXT NOT NULL,
    sources_json TEXT NOT NULL,         -- JSON array of YouTube channel URLs/RSS/watch folders
    branding_preset_json TEXT NOT NULL, -- Subtitle font, highlight colors, crop mode, watermark
    metadata_preset_json TEXT NOT NULL, -- Tone, hashtag pool, link-in-bio CTA
    max_daily_clips INTEGER DEFAULT 3,
    enabled INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Master Job Queue Table
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,          -- 'youtube_url', 'youtube_channel', 'local_file'
    title TEXT,
    duration_seconds REAL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    raw_video_path TEXT,
    audio_path TEXT,
    transcript_json TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    error_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- Generated Clips Table
CREATE TABLE IF NOT EXISTS clips (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    duration_seconds REAL NOT NULL,
    virality_score REAL DEFAULT 0.0,
    hook_text TEXT,
    video_path TEXT,
    caption_path TEXT,
    title TEXT,
    description TEXT,
    hashtags TEXT,
    approved INTEGER DEFAULT 0,         -- 0: Pending Review, 1: Approved, 2: Rejected
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE,
    FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
);

-- System Event Logs Table
CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    level TEXT NOT NULL,                -- 'INFO', 'WARNING', 'ERROR'
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

### 2. State Machine Lifecycle (`core/queue.py`)

You must enforce the following strict 8-stage state machine:

```mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> DOWNLOADING : Lock Job
    DOWNLOADING --> TRANSCRIBING : Download Done
    TRANSCRIBING --> ANALYZING : STT Done
    ANALYZING --> CLIPPING : LLM Score Done
    CLIPPING --> CAPTIONING : Vertical Render Done
    CAPTIONING --> METADATA : Subtitles Burned
    METADATA --> COMPLETED : Metadata Packed
    
    DOWNLOADING --> FAILED : Timeout / Error
    TRANSCRIBING --> FAILED : API Error
    ANALYZING --> FAILED : Invalid JSON
    CLIPPING --> FAILED : FFmpeg Error
    CAPTIONING --> FAILED : ASS Render Error
    METADATA --> FAILED : LLM Error
    
    FAILED --> PENDING : Auto-Retry (If retry_count < max_retries)
```

---

## 📜 Mandatory Engineering Guidelines & Strict Rules

> [!IMPORTANT] **Rule 1: Atomic Transactions**
> Every state update in `queue.py` must execute inside a `with db.transaction():` context block. Never leave database connections open or write to SQLite without immediate commit.

> [!IMPORTANT] **Rule 2: Crash & Reboot Auto-Recovery**
> When `main.py --daemon` starts:
> 1. Query all jobs where `status NOT IN ('COMPLETED', 'FAILED')`.
> 2. Inspect filesystem for downloaded artifacts (`raw_video_path`, `audio_path`, `transcript_json`).
> 3. Reset state to the last verified completed step (e.g. if raw video exists on disk, do NOT re-download; resume directly from `TRANSCRIBING`).

> [!IMPORTANT] **Rule 3: Round-Robin Scheduling Across N Accounts**
> Do NOT process 10 jobs sequentially for Account 01 while Account 02 waits indefinitely. Implement a fair round-robin selector:
> `SELECT * FROM jobs WHERE status = 'PENDING' GROUP BY account_id ORDER BY updated_at ASC`.

> [!IMPORTANT] **Rule 4: Zero Memory Leak / Resource Cleanup**
> Ensure SQLite connection pools use WAL mode (`PRAGMA journal_mode=WAL;`) and close gracefully on `SIGINT` / `SIGTERM` signals.

---

## 🔄 Step-by-Step Implementation Workflow

1. **Step 1: Build `core/config.py`**
   - Parse `config.json` and `.env` files.
   - Validate API keys (`GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`).
   - Define fallback default paths (`storage/clipit.db`).

2. **Step 2: Build `core/db.py`**
   - Create SQLite connection context manager with thread locking.
   - Run table initialization migrations (`CREATE TABLE IF NOT EXISTS`).
   - Implement query helper functions (`execute_read`, `execute_write`, `execute_transaction`).

3. **Step 3: Build `core/queue.py`**
   - Implement `JobQueueManager` class.
   - Add state transition functions: `advance_job(job_id, next_status, payload)`.
   - Add job error handler: `fail_job(job_id, error_message)` with automatic retry counter increment.
   - Add round-robin fetcher: `get_next_pending_job()`.

4. **Step 4: Build `main.py`**
   - CLI flags: `--daemon` (runs background loop), `--add-url` (enqueues single link), `--add-account` (creates account profile), `--status` (prints queue metrics).
   - Signal handlers for clean shutdown (`signal.SIGINT`, `signal.SIGTERM`).

---

## 🛡️ Error Handling, Fail-Fast Mechanics & Edge Cases

| Edge Case / Failure | Mandatory Action / Guard |
| :--- | :--- |
| **Database File Locked (`sqlite3.OperationalError: database is locked`)** | Enable WAL mode + set `busy_timeout = 10000` (10s) in SQLite connection setup. |
| **Daemon Killed Mid-Stage** | On daemon startup, check if files exist on disk before running expensive steps. |
| **Account Deleted While Job Running** | Foreign key `ON DELETE CASCADE` automatically removes child jobs and clips. |
| **Infinite Error Retry Loop** | Enforce `retry_count < max_retries` (default 3). If exceeded, mark status `FAILED`. |

---

## 🧪 Verification & Definition of Done

Before marking your work complete, you must verify:

1. **Database Creation**: `python -c "from core.db import init_db; init_db()"` creates `storage/clipit.db` with all tables.
2. **State Machine Test**: Enqueue a dummy job, advance it through all 8 stages, and verify state in SQLite.
3. **Crash Recovery Test**: Set job status to `TRANSCRIBING`, kill the process, restart `main.py`, and verify job resumes from `TRANSCRIBING`.
4. **Clean Shutdown**: Run `main.py --daemon`, hit `Ctrl+C`, and confirm zero WAL corruption or hanging processes.

---

## 🤝 Inter-Agent Interaction Protocols

- **Interface with Agent 02 (AI & Ingestion)**: Provide `queue.get_pending_watcher_jobs()` and `queue.advance_job(job_id, 'TRANSCRIBING', payload)`.
- **Interface with Agent 03 (Media Engineer)**: Provide clip timestamps payload and accept rendered `clip_path` and `caption_path`.
- **Interface with Agent 04 (Web UI)**: Provide read-only query endpoints for `SELECT * FROM clips WHERE approved = 0`.
- **Interface with Agent 05 (Mobile OS)**: Respect daemon shutdown signals passed from `scripts/start.sh`.

---

## 📄 Reference Code Snippet (`core/queue.py`)

```python
import sqlite3
from typing import Optional, Dict, Any
from core.db import get_db_connection
from core.logger import logger

class JobQueueManager:
    def __init__(self, db_path: str = "storage/clipit.db"):
        self.db_path = db_path

    def advance_stage(self, job_id: str, current_stage: str, next_stage: str, updates: Optional[Dict[str, Any]] = None) -> bool:
        with get_db_connection(self.db_path) as conn:
            cursor = conn.cursor()
            query = "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP"
            params = [next_stage]
            
            if updates:
                for key, val in updates.items():
                    query += f", {key} = ?"
                    params.append(val)
                    
            query += " WHERE id = ? AND status = ?"
            params.extend([job_id, current_stage])
            
            cursor.execute(query, params)
            if cursor.rowcount > 0:
                logger.info(f"Job {job_id} advanced from {current_stage} -> {next_stage}")
                return True
            logger.warning(f"Failed to advance Job {job_id} from {current_stage}")
            return False
```



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet / Opencode Zen (-free)