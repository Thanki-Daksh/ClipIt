#!/data/data/com.termux/files/usr/bin/bash
# =============================================================================
# ClipIt → scripts/start.sh  (Agent 05: Mobile Daemon & OS Runtime)
# -----------------------------------------------------------------------------
# Termux background daemon launcher.
#   - Single-instance PID lock at $ROOT/storage/clipit.pid
#     (peer key: storage/clipit.pid is Agent 01's PID tracker contract)
#   - Acquires termux-wake-lock when running on Android/Termux
#   - Launches main.py --daemon in the background, logs to storage/logs/
#   - Launches the battery/thermal/memory guardian after the daemon starts
#
# Usage:   ./start.sh            (normal daemon start)
#          DRY_RUN=1 ./start.sh  (validate POSIX/syntax only, no side effects)
#          DEV=1 ./start.sh      (skip termux-wake-lock, for desktop dev)
# =============================================================================
set -euo pipefail

# --- Resolve project root & key paths ---------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
PID_FILE="${ROOT_DIR}/storage/clipit.pid"
LOG_DIR="${ROOT_DIR}/storage/logs"
DAEMON_LOG="${LOG_DIR}/daemon.log"
MONITOR_LOG="${LOG_DIR}/monitor.log"
MONITOR="termux_monitor.py"

mkdir -p "${LOG_DIR}"

log()  { echo "[${0##*/}] $(date '+%F %T') $*"; }
fail() { log "ERROR: $*"; exit 1; }
warn() { log "WARN: $*"; }

# -----------------------------------------------------------------------------
# 0) Optional dry-run: POSIX/syntax validation only.
# -----------------------------------------------------------------------------
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "DRY-RUN: ROOT=${ROOT_DIR}"
  log "DRY-RUN: PID_FILE=${PID_FILE}"
  log "DRY-RUN: DAEMON_LOG=${DAEMON_LOG}"
  [[ -x "${SCRIPT_DIR}/${MONITOR}" ]] || log "DRY-RUN WARN: ${MONITOR} not executable"
  command -v python3 >/dev/null 2>&1 || { log "DRY-RUN ERROR: python3 not on PATH"; exit 1; }
  echo "DRY-RUN OK"
  exit 0
fi

# ---------------------------------------------------------------------------
# 2) Single-instance lockdown — refuse to double-start.
#    Peer contract (Agent 01): storage/clipit.pid holds the live daemon PID.
# ---------------------------------------------------------------------------
if [[ -f "${PID_FILE}" ]]; then
  EXISTING_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${EXISTING_PID}" ]] && kill -0 "${EXISTING_PID}" 2>/dev/null; then
    log "ClipIt daemon already running (PID ${EXISTING_PID}). Use stop.sh first."
    exit 1
  fi
  log "Stale PID file found (${EXISTING_PID:-empty}); removing."
  rm -f "${PID_FILE}"
fi

# ---------------------------------------------------------------------------
# 3) Acquire Android wake-lock (CPU keepalive) — skip on desktop dev.
# ---------------------------------------------------------------------------
if [[ "${DEVICE_RUN:-0}" != "1" && "${TERMUX_VERSION:-}" != "" ]]; then
  if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock || warn "termux-wake-lock failed"
  else
    warn "termux-wake-lock not found on PATH"
  fi
fi

# ---------------------------------------------------------------------------
# 4) Start the daemon loop in the background.
#    NOTE: main.py --daemon is built by Agent 01 (Systems Architect).
#    If it is not present yet, we still bring the runtime up and log clearly.
# ---------------------------------------------------------------------------
cd "${ROOT_DIR}"
export PYTHONUNBUFFERED=1

if [[ -f "main.py" ]]; then
  nohup python3 main.py --daemon >> "${DAEMON_LOG}" 2>&1 &
  echo $! > "${PID_FILE}"
  # Persist daemon PID so Agent 01's tracker + stop.sh agree.
  log "Daemon launched (PID $(cat "${PID_FILE}")). Logs: ${DAEMON_LOG}"
else
  echo "main.py (Agent 01 deliverable) not found yet — daemon not started."
  exit 1
fi

# ---------------------------------------------------------------------------
# 5) Launch the battery/thermal/memory guardian alongside the daemon.
# ---------------------------------------------------------------------------
if [[ -f "${SCRIPT_DIR}/${MONITOR}" ]]; then
  nohup python3 "${SCRIPT_DIR}/${MONITOR}" >> "${MONITOR_LOG}" 2>&1 &
  echo $! > "${ROOT_DIR}/storage/monitor.pid"
  log "Health guardian started (PID $(cat "${ROOT_DIR}/storage/monitor.pid")). Logs: ${MONITOR_LOG}"
else
  log "WARN: ${MONITOR} missing — running without battery/thermal guard."
fi

log "ClipIt daemon is up. Stop with: ./stop.sh"