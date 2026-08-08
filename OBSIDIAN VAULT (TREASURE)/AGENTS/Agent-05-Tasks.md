> [!LAUNCH] 🚀 **SKILL STARTUP ACTIVATION & MODEL CONFIGURATION**
> - **Workspace Directory**: `C:/Users/Admin/OneDrive/Desktop/ClipIt/modules`
> - **hermes Activation Command (DeepSeek v4 Flash-Free 200k - Primary)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt" && clear && hermes`
> - **agy Activation Command (Gemini 3.6 Flash)**: `cd "C:/Users/Admin/OneDrive/Desktop/ClipIt/modules" && clear && agy`
> - **SKILL**: `/ClipIt-Mobile-Daemon-OS-Runtime`

# 📋 AGENT 05: TASKS BOARD (SOCIAL PUBLISHER & API INTEGRATOR)

- 🤖 **[[Agent-05-Social-Publisher-API-Integrator| Back to Agent 05 Hub]]**

## 📌 Social Publisher Matrix (15 Tasks — all [x] COMPLETED, verified 2026-08-08)

- [x] Build `modules/publisher_yt.py` Shorts Engine (Data API v3 resumable upload) — TSK-A05-01
- [x] Build `modules/publisher_ig.py` Reels Engine (Graph API container workflow) — TSK-A05-02
- [x] Build `core/auth.py` OAuth Token Refresh (YT refresh-grant + IG long-lived) — TSK-A05-03
- [x] Upload Retry & Rate Limit Engine (exponential backoff ≤3 attempts) — TSK-A05-04
- [x] Publish Schedule Time Dispatcher (`--publish-scheduled` + ledger JSON) — TSK-A05-05
- [x] Mock Publisher Mode (`--mock` / `CLIPIT_MOCK=1`, simulated uploads) — TSK-A05-06
- [x] Video Upload Progress Telemetry (chunked bytes / 3-stage phases) — TSK-A05-07
- [x] Multi-Account Token Rotator (`core.auth.CredentialPool` round-robin) — TSK-A05-08
- [x] Instagram Container Status Poller (`status_code == FINISHED`) — TSK-A05-09
- [x] Video Category & Privacy Flags (`categoryId=22`, `privacyStatus`) — TSK-A05-10
- [x] Automatic Hashtags & Caption Injector (`#Shorts` / `#Reels`) — TSK-A05-11
- [x] Upload Quota Safety Guard (6 YT uploads / account / day) — TSK-A05-12
- [x] Failed Upload Log & Audit Trail (`job_logs` table) — TSK-A05-13
- [x] Custom Cover Frame Uploader (`thumbnails.set` PNG poster) — TSK-A05-14
- [x] Post-Publish Verification Probe (`verify()` live/url probe) — TSK-A05-15

## 📟 Legacy Daemon Tasks (still shipped — scripts/ intact, superseded role)
- [x] Termux daemon launcher (`scripts/start.sh`) w/ wake-lock
- [x] Clean shutdown (`scripts/stop.sh`) w/ wake-lock release
- [x] Battery & thermal monitor (`scripts/termux_monitor.py`)
- [x] Boot auto-start helper (`scripts/boot_recovery.sh`)
- [x] Wi-Fi/metered-network detection + disk hold + Termux-Boot service + CPU governor switch

## ✅ Verification Evidence
- `python -m pytest tests/` → **218 passed, 1 skipped** (2026-08-08).
- 26 new feature tests in `tests/test_publisher_features.py` covering TSK-A05-03..15.
- CLI smokes green: `--verify-config` (exit 1 = correct no-creds desktop signal),
  `--list` (read-only legacy DB), `--mock --publish-scheduled` (due-clip dispatch).

### ⚙️ Recommended Model & Effort Configuration
- **Free Context Engine**: deepseek-v4-flash-free (OpenCode Zen - 200k Context Window)
- **Primary Model**: Opencode Zen (-free) / Gemini 3.6 Flash
- **Effort Level**: Medium Effort
- **Fallback Model**: Gemini 3.6 Flash