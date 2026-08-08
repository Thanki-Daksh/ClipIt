# 🤖 Agent 05 Hub — Social Publisher & API Integrator

> [!ABSTRACT] **Agent 05: Social Publisher & API Integrator**
> Owns the ClipIt auto-publishing layer: YouTube Shorts and Instagram Reels
> engines, OAuth lifecycle, retry/rate limiting, scheduling, quotas, audit
> trail, cover frames, and post-publish verification.

---

## 🔗 Hub Connections
- 👑 **[[CEO-Operational-Guide| CEO Orchestrator Guide]]**
- 📋 **[[Task-Assignment-Agent-05| Task Assignment]]**
- 📝 **[[Agent-05-Daily-Log| Daily Log]]**
- ✅ **[[Agent-05-Tasks| Task Checklist]]**
- 🕵️ **[[Agent-05-Peer-Review| Peer Reviews]]**
- 📐 **[[Agent-05-Architecture| Architecture]]**

---

## 🚀 Mission
Keep ClipIt publishing approved clips to YouTube Shorts & Instagram Reels
24/7 — resilient to rate limits, token expiry, quota exhaustion, and
transient API failures — without ever writing to pipeline state.

## 🧩 Owned Modules

| File | Role |
| :--- | :--- |
| `core/auth.py` | OAuth refresh (YT/IG), CredentialPool rotator, UploadQuota, audit trail, schedule ledger |
| `modules/publisher_yt.py` | YouTube Data API v3 resumable Shorts uploader |
| `modules/publisher_ig.py` | Instagram Graph API two-phase Reels publisher |

## 🧠 Key Contracts
- YouTube REQUIRES OAuth (access token OR refresh trio); API key cannot upload.
- IG Graph API needs a PUBLIC video URL — never a local file.
- Both modules: injectable HTTP (never import-time network), `--dry-run`,
  schema-tolerant approved-clip discovery (`PRAGMA table_info`).
- Quota: 6 YT uploads/account/day (env `CLIPIT_YT_DAILY_QUOTA`).
- Audit: every failure → `job_logs` table row (`core.auth.audit_event`).
- Schedule: JSON ledger per clip (`storage/logs/publish_schedule.json`).

## 📊 Verification Recipe (desktop, no creds)
1. `python -m pytest tests/ -q` → full suite green.
2. `python -m modules.publisher_yt --verify-config` → exit 1 (missing secrets is CORRECT on desktop).
3. `python -m modules.publisher_yt --list` → read-only approved clips.
4. `python -m modules.publisher_yt --mock --publish-all` → simulated publishes.