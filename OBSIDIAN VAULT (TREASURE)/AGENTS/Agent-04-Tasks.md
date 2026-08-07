> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/ui`
> - **agy Activation Command (Gemini 3.6 Flash / Claude 3.5 Sonnet)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && agy`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/ui" && clear && hermes`
> - **SKILL**: `/ClipIt-Frontend-Mobile-UI-Dev`

# 📋 AGENT 04: TASKS BOARD

- 💻 **[[Agent-04-Frontend-Mobile-UI-Dev| Back to Agent 04 Hub]]**

## 📌 Active Tasks
- [x] Build FastAPI localhost web server (`ui/app.py`)
- [x] Build mobile dark-mode HTML template (`ui/templates/index.html`)
- [x] Build 9:16 HTML5 video preview card & modal editor (`ui/static/js/app.js`)
- [x] Implement 1-tap clip approval REST API (`/api/clips/{id}/approve`)



### 👁️ Multimodal Vision Capability (UI AUDIT)
- **Model**: Playwright Screenshot Prober / Vision LLM
- **Vision Tasks**:
  1. **Mobile Layout Verification**: Capture and inspect mobile viewport screenshots (375px-430px) of http://localhost:8000.
  2. **9:16 Player Alignment**: Confirm video player cards render cleanly without overflow or broken aspect ratio margins.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Claude 3.5 Sonnet / Gemini 3.6 Flash
- **Effort Level**: High Effort
- **Fallback Model**: GPT-4o