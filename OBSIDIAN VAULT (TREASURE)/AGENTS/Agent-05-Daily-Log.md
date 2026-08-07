> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/scripts" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`

# 📅 AGENT 05: DAILY ACTIVITY LOG

- 📱 **[[Agent-05-Mobile-Daemon-OS-Runtime| Back to Agent 05 Hub]]**

## 2026-08-07
- Specified Termux wake-lock script flags and PID file mechanics.
- Set thermal pause ceiling to 43°C to prevent phone battery degradation.
- **BUILT `scripts/start.sh`** — single-instance PID lock (storage/clipit.pid), termux-wake-lock acquisition, launches `main.py --daemon` + `termux_monitor.py`; `DRY_RUN=1` → POSIX validation. Verified: `bash -n` + DRY-RUN pass.
- **BUILT `scripts/stop.sh`** — TERM→KILL graceful shutdown of daemon (storage/clipit.pid) + monitor (storage/monitor.pid), releases `termux-wake-unlock`, cleans PID files. Verified: `bash -n` pass.
- **BUILT `scripts/termux_monitor.py`** — guardian reads battery %, plug state, temp, free RAM, free disk. Pauses (writes monitor.paused flag + JSON state) when <15% battery unplugged, >43°C, or <200MB RAM; warns on <500MB disk (Agent 03 audit). Exponential backoff 10s→300s. VERIFIED: `--once --json` → status OK; simulated phone (batt12/unplugged/47C/90MB/200MB) → `status=PAUSED` with all 4 reasons + pause flag written.
- **BUILT `scripts/boot_recovery.sh`** — Termux:Boot helper (copy to ~/.termux/boot/), waits for boot settle, no double-start, re-runs start.sh. Verified: `bash -n` pass.



### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Opencode Zen (-free) / Gemini 3.6 Flash
- **Effort Level**: Medium Effort
- **Fallback Model**: Gemini 3.6 Flash