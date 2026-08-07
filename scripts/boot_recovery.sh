#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# ClipIt → scripts/boot_recovery.sh  (Agent 05: Mobile Daemon & OS Runtime)
# -----------------------------------------------------------------------------
# Automatic recovery: restarts the ClipIt daemon after the Android phone
# reboots. Designed for the Termux:Boot add-on:
#
#   mkdir -p ~/.termux/boot
#   cp scripts/boot_recovery.sh ~/.termux/boot/clipit_boot.sh
#   chmod +x ~/.termux/boot/clipit_boot.sh
#
# Termux:Boot executes every file in ~/.termux/boot/ on device boot.
# This script:
#   - waits for boot to settle (avoids racing the storage mount)
#   - refuses to double-start if the daemon is already running
#   - re-acquires the wake-lock and relaunches daemon + monitor via start.sh
#
# Usage:  ./boot_recovery.sh [--force]
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${ROOT_DIR}/storage/clipit.pid"
BOOT_SETTLE_SEC=20

log()  { echo "[${0##*/}] $(date '+%F %T') $*"; }

# ---------------------------------------------------------------------------
# Wait for the filesystem to settle after boot.
# ---------------------------------------------------------------------------
log "Waiting ${BOOT_SETTLE_SEC}s for boot to settle..."
sleep "${BOOT_SETTLE_SEC}"

# ---------------------------------------------------------------------------
# Single-instance guard: if start.sh is already running, do nothing.
# ---------------------------------------------------------------------------
if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" 2>/dev/null; then
    log "Daemon already running (PID ${EXISTING_PID}); skipping recovery."
    exit 0
  fi
  log "Removing stale PID file from before reboot."
  rm -f "${PID_FILE}"
fi

if [[ "${1:-}" != "--force" ]]; then
  # Only auto-start if the daemon is expected (starts.sh created before).
  if [[ ! -x "${ROOT_DIR}/main.py" && ! -f "${ROOT_DIR}/main.py" ]]; then
    log "main.py not present; nothing to recover yet."
    exit 0
  fi
fi

log "Recovering ClipIt daemon..."
"${SCRIPT_DIR}/start.sh" || log "start.sh exited non-zero — see ${ROOT_DIR}/storage/logs/daemon.log"
log "Recovery done."