> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && hermes`
> - **SKILL**: `/ClipIt-Systems-Architect`

# 📋 AGENT 01: TASKS BOARD

- 🎯 **[[Agent-01-Systems-Architect| Back to Agent 01 Hub]]**

## 📌 Active Tasks
- [x] Design SQLite Schema (`accounts`, `jobs`, `clips`, `logs`)
- [x] Implement `core/db.py` connection manager & WAL mode
- [x] Implement `core/queue.py` state machine manager
- [x] Build crash recovery auto-resume mechanism
- [x] Build round-robin scheduler across N accounts
- [x] Connect QueueEngine to main.py --daemon auto-pipeline loop
- [x] Enforce storage/{account_id}/raw and /clips directory segregation
- [x] Implement Crash Re-Queue Engine for stuck mid-stage jobs
- [x] Implement System Healthcheck REST API (`GET /health` in `core/health.py`)



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet / Opencode Zen (-free)