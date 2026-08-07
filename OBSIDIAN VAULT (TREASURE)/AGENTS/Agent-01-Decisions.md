> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && hermes`
> - **SKILL**: `/ClipIt-Systems-Architect`

# ⚖️ AGENT 01: DECISIONS LOG

- 🎯 **[[Agent-01-Systems-Architect| Back to Agent 01 Hub]]**

## ADR-001: SQLite WAL Mode for High Concurrency
- **Status**: Approved
- **Decision**: Set `PRAGMA journal_mode = WAL;` to prevent database locking errors during concurrent reads from Web UI and writes from Background Daemon.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet / Opencode Zen (-free)