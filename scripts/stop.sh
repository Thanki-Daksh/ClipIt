#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# ClipIt → scripts/stop.sh  (Agent 05: Mobile Daemon & OS Runtime)
# -----------------------------------------------------------------------------
# Clean shutdown + wake-lock release.
#   - Reads daemon PID from storage/clipit.pid and TERMinates it.
#   - Stops the health monitor too (storage/monitor.pid).
#   - Releases termux-wake-unlock and removes stale PID files.
#
# Usage:  ./stop.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${ROOT_DIR}/storage/clipit.pid"
MONITOR_PID_FILE="${ROOT_DIR}/storage/monitor.pid"
LOG_DIR="${ROOT_DIR}/storage/logs"

log()  { echo "[${0##*/}] $(date '+%F %T') $*"; }

stop_one() {
  local name="$1"; local file="$2"
  if [[ ! -f "${file}" ]]; then
    log "${name}: no PID file — nothing to stop."
    return
  fi
  local pid
  pid="$(cat "${file}" 2>/dev/null || true)"
  rm -f "${file}"
  if [[ -z "${pid}" || "${pid}" == "0" ]]; then
    log "${name}: stale/empty PID file removed."
    return
  fi
  if kill -0 "${pid}" 2>/dev/null; then
    kill -TERM "${pid}" 2>/dev/null || true
    # give it up to 5s to exit gracefully
    for _ in 1 2 3 4 5; do
      kill -0 "${pid}" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "${pid}" 2>/dev/null; then
      kill -KILL "${pid}" 2>/dev/null || true
      log "${name}: forced KILL of PID ${pid}"
    else
      log "${name}: PID ${pid} terminated."
    fi
  else
    log "${name}: process ${pid} not running."
  fi
}

# Stop monitor first (it only watches), then the daemon.
stop_one "Monitor" "${MONITOR_PID_FILE}"
stop_one "Daemon"  "${PID_FILE}"

# Release the Android CPU keepalive lock.
if command -v termux-wake-unlock >/dev/null 2>&1; then
  termux-wake-unlock && log "wake-lock released."
else
  log "termux-wake-unlock not found — nothing to release (or dev mode)."
fi

log "ClipIt daemon + monitor stopped cleanly."