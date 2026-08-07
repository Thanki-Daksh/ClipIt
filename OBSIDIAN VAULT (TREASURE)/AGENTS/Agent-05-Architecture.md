> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`

# 🏗️ AGENT 05: ARCHITECTURE

- 📱 **[[Agent-05-Mobile-Daemon-OS-Runtime| Back to Agent 05 Hub]]**

## 📱 Mobile Runtime Architecture
- **Core Files**: `scripts/start.sh`, `scripts/stop.sh`, `scripts/termux_monitor.py`
- **Wake-Lock**: `termux-wake-lock` / `termux-wake-unlock`
- **Thermal Threshold**: Pause at `> 43.0 °C`



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Opencode Zen (-free) / Gemini 3.6 Flash
- **Effort Level**: Medium Effort
- **Fallback Model**: Gemini 3.6 Flash