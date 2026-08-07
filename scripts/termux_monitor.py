#!/data/data/com.termux/files/usr/bin/env python3
"""
ClipIt → scripts/termux_monitor.py  (Agent 05: Mobile Daemon & OS Runtime)
==========================================================================
Battery, thermal, memory, and disk-space guardian that runs alongside the
ClipIt daemon on Android (Termux) or desktop.

Safeguards (per Plan 04 / Agent 05 spec):
  - Battery: if level < BATTERY_PAUSE_PCT (15) while UNPLUGGED -> PAUSE
  - Thermal : if temperature > THERMAL_PAUSE_C (43.0 °C)        -> PAUSE
  - Memory  : if free RAM < MEMORY_PAUSE_MB (200 MB)            -> PAUSE
  - Disk    : if free disk < DISK_RENDER_MIN_MB (500 MB)        -> WARN
             (peer audit for Agent 03: FFmpeg render needs > 500 MB free)

When paused, the guardian writes a heartbeat + pause flag that the daemon
polls, so Agent 01's main.py can skip heavy pipeline steps while the phone
is hot / low on battery. It also applies an exponential backoff sleep cycle
(10s -> 30s -> 60s -> 120s -> 300s max) when healthy, and checks every
CHECK_INTERVAL_CRITICAL (10s) while in a degraded state.

Usage:
  python3 scripts/termux_monitor.py [--interval 30] [--once] [--json]
    --interval N   check every N seconds (default 30)
    --once         single check then exit (used by tests / cron)
    --json         print the latest status dict as JSON (with --once)

State files (written to storage/):
  storage/logs/monitor_state.json  -> latest snapshot (machine readable)
  storage/monitor.pid              -> guardian's own PID (stop.sh reads it)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Thresholds (spec values — do not tune casually)
# ---------------------------------------------------------------------------
BATTERY_PAUSE_PCT = 15          # pause processing below 15% when unplugged
THERMAL_PAUSE_C = 43.0          # pause processing above 43.0 °C
MEMORY_PAUSE_MB = 200           # pause if free RAM below 200 MB
DISK_RENDER_MIN_MB = 500        # warn if free disk below 500 MB (Agent 03)
CHECK_INTERVAL_SEC = 30         # default healthy polling interval
CHECK_INTERVAL_CRITICAL = 10    # fast re-check while degraded
BACKOFF_MAX_SEC = 300           # exponential backoff ceiling

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
STORAGE_DIR = ROOT_DIR / "storage"
LOG_DIR = STORAGE_DIR / "logs"
STATE_FILE = LOG_DIR / "monitor_state.json"
PID_FILE = STORAGE_DIR / "monitor.pid"
PAUSE_FLAG = STORAGE_DIR / "monitor.paused"
DAEMON_PID_FILE = STORAGE_DIR / "clipit.pid"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Sensor readers — each returns a value or None when the source is missing.
# ---------------------------------------------------------------------------
def battery_level() -> int | None:
    """Battery percent via Termux:API; falls back to sysfs on Linux."""
    try:
        out = subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            data = json.loads(out.stdout)
            pct = data.get("percentage")
            return int(pct) if isinstance(pct, (int, float)) else None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    # Fallback: /sys/class/power_supply/BAT*/capacity
    for cap in sorted(Path("/sys/class/power_supply").glob("BAT*/capacity")):
        try:
            return int(cap.read_text().strip())
        except (OSError, ValueError):
            continue
    return None


def plugged_in() -> bool | None:
    """True when charging / plugged. None when unknown."""
    try:
        out = subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            data = json.loads(out.stdout)
            return str(data.get("plugged", "")).upper() != "UNPLUGGED"
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    try:
        for status in sorted(Path("/sys/class/power_supply").glob("BAT*/status")):
            return "CHARG" in status.read_text().upper()
    except OSError:
        pass
    return None


def battery_temp_c() -> float | None:
    """Battery temperature in °C via Termux:API (returns already °C)."""
    try:
        out = subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=5
        )
        if out.returncode == 0:
            data = json.loads(out.stdout)
            temp = data.get("temperature")
            if isinstance(temp, (int, float)):
                return float(temp)
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        pass
    return None


def cpu_temp_c() -> float | None:
    """Max thermal-zone temperature in °C from sysfs (Linux/Android)."""
    zones = sorted(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    temps: list[float] = []
    for z in zones:
        try:
            millideg = int(z.read_text().strip())
            temps.append(millideg / 1000.0)
        except (OSError, ValueError):
            continue
    return max(temps) if temps else None


def free_ram_mb() -> int | None:
    """Free memory in MB (MemAvailable on Linux, TotalVisible on Android)."""
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable"):
                    return int(line.split()[1]) // 1024
                if line.startswith("MemFree"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def free_disk_mb() -> int | None:
    """Free disk on the project volume in MB."""
    try:
        usage = shutil.disk_usage(ROOT_DIR)
        return int(usage.free // (1024 * 1024))
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Guardian core
# ---------------------------------------------------------------------------
def check_once() -> dict:
    """Read all sensors, evaluate safeguards, persist state. Returns dict."""
    bat = battery_level()
    plug = plugged_in()
    temp = battery_temp_c() or cpu_temp_c()
    ram = free_ram_mb()
    disk = free_disk_mb()

    reasons: list[str] = []
    if bat is not None and plug is False and bat < BATTERY_PAUSE_PCT:
        reasons.append(f"battery {bat}% < {BATTERY_PAUSE_PCT}% (unplugged)")
    if temp is not None and temp > THERMAL_PAUSE_C:
        reasons.append(f"temp {temp:.1f}C > {THERMAL_PAUSE_C}C")
    if ram is not None and ram < MEMORY_PAUSE_MB:
        reasons.append(f"free RAM {ram}MB < {MEMORY_PAUSE_MB}MB")

    status = "PAUSED" if reasons else "OK"
    if disk is not None and disk < DISK_RENDER_MIN_MB:
        status = "LOWDISK" if status == "OK" else status
        reasons.append(f"free disk {disk}MB < {DISK_RENDER_MIN_MB}MB (Agent 03 audit)")

    # Daemon liveness check (peer audit for Agent 01).
    daemon_pid = None
    if DAEMON_PID_FILE.exists():
        try:
            daemon_pid = int(DAEMON_PID_FILE.read_text().strip())
        except ValueError:
            daemon_pid = None

    state = {
        "ts": now_iso(),
        "status": status,
        "paused": status == "PAUSED",
        "reasons": reasons,
        "battery_pct": bat,
        "plugged": plug,
        "temp_c": round(temp, 1) if temp is not None else None,
        "free_ram_mb": ram,
        "free_disk_mb": disk,
        "daemon_pid": daemon_pid,
        "daemon_alive": bool(daemon_pid) and _pid_alive(daemon_pid),
        "thresholds": {
            "battery_pause_pct": BATTERY_PAUSE_PCT,
            "thermal_pause_c": THERMAL_PAUSE_C,
            "memory_pause_mb": MEMORY_PAUSE_MB,
            "disk_render_min_mb": DISK_RENDER_MIN_MB,
        },
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")

    # Pause flag: daemon polls this file before heavy pipeline steps.
    if state["paused"]:
        PAUSE_FLAG.write_text(now_iso(), encoding="utf-8")
    else:
        PAUSE_FLAG.unlink(missing_ok=True)

    return state


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _log(state: dict) -> None:
    line = (
        f"[{state['ts']}] status={state['status']} "
        f"battery={state['battery_pct']}% plugged={state['plugged']} "
        f"temp={state['temp_c']}C ram={state['free_ram_mb']}MB "
        f"disk={state['free_disk_mb']}MB daemon_alive={state['daemon_alive']}"
    )
    if state["reasons"]:
        line += " | " + "; ".join(state["reasons"])
    print(line, flush=True)


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ClipIt battery/thermal/memory guardian")
    ap.add_argument("--interval", type=int, default=CHECK_INTERVAL_SEC,
                    help=f"healthy check interval in seconds (default {CHECK_INTERVAL_SEC})")
    ap.add_argument("--once", action="store_true", help="single check, then exit")
    ap.add_argument("--json", action="store_true", help="print state as JSON")
    args = ap.parse_args()

    # Record guardian PID for stop.sh.
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    if args.once:
        state = check_once()
        print(json.dumps(state, indent=2) if args.json else "")
        return 0 if state["paused"] else (2 if state["status"] == "LOWDISK" else 0)

    # Continuous loop with exponential backoff (10s -> ... -> 300s).
    backoff = CHECK_INTERVAL_CRITICAL
    print(f"[monitor] guardian started. interval={args.interval}s "
          f"backoff_max={BACKOFF_MAX_SEC}s pid={os.getpid()}", flush=True)
    while True:
        state = check_once()
        _log(state)
        if state["paused"]:
            backoff = CHECK_INTERVAL_CRITICAL  # degraded -> re-check fast
            time.sleep(backoff)
        else:
            time.sleep(min(backoff, args.interval))
            backoff = min(backoff * 2, BACKOFF_MAX_SEC) if state["status"] == "OK" else CHECK_INTERVAL_CRITICAL


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        PAUSE_FLAG.unlink(missing_ok=True)
        print("[monitor] stopped by user; pause flag cleared.", flush=True)
        raise SystemExit(0)
