> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`

# 📋 AGENT 05: TASKS BOARD

- 📱 **[[Agent-05-Mobile-Daemon-OS-Runtime| Back to Agent 05 Hub]]**

## 📌 Active Tasks
- [x] Build Termux daemon launcher (`scripts/start.sh`) with wake-lock acquisition
- [x] Build clean shutdown script (`scripts/stop.sh`) with wake-lock release
- [x] Build battery & thermal monitor (`scripts/termux_monitor.py`)
- [x] Build Android boot auto-start helper script (`scripts/boot_recovery.sh`)
- [x] Build Wi-Fi/metered-network detection (pause downloads off Wi-Fi)
- [x] Build 1 GB disk storage hold (pause pipeline below 1 GB free)
- [x] Build Termux-Boot auto-start service (`boot_recovery.sh --install`)
- [x] Build CPU low-power governor switch (thermal -> concurrency.json)
- [x] Build YouTube Shorts auto-poster (`modules/publisher_yt.py`, Data API v3 resumable upload)
- [x] Build Instagram Reels auto-publisher (`modules/publisher_ig.py`, Graph API two-phase publish)



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Opencode Zen (-free) / Gemini 3.6 Flash
- **Effort Level**: Medium Effort
- **Fallback Model**: Gemini 3.6 Flash