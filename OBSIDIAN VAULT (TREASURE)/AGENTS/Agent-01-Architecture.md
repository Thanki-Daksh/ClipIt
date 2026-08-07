> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/core`
> - **agy Activation Command (Gemini 3.6 Flash - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/core" && clear && hermes`
> - **SKILL**: `/ClipIt-Systems-Architect`

# 🏗️ AGENT 01: ARCHITECTURE

- 🎯 **[[Agent-01-Systems-Architect| Back to Agent 01 Hub]]**

## 🗄️ Database Schemas & State Engine
- **Core Files**: `core/db.py`, `core/queue.py`, `main.py`
- **State Machine**: `PENDING` ➔ `DOWNLOADING` ➔ `TRANSCRIBING` ➔ `ANALYZING` ➔ `CLIPPING` ➔ `CAPTIONING` ➔ `METADATA` ➔ `COMPLETED`



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Gemini 3.6 Flash (agy subscription)
- **Effort Level**: High Effort
- **Fallback Model**: Claude 3.5 Sonnet / Opencode Zen (-free)