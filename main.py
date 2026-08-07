#!/usr/bin/env python3
"""
ClipIt CLI Entrypoint & Daemon Supervisor
==========================================
Agent 01 (Principal Systems Architect) owns this file.

Commands:
    python main.py --init                        Create/upgrade the DB schema
    python main.py --add-account ...             Register a new content account
    python main.py --add-url <URL> --account <>  Enqueue a job
    python main.py --list                        Show queues / accounts / clips
    python main.py --daemon                      Run the background supervisor loop

Flags on the daemon:
    --once             Run a single scheduler tick and exit (for tests/cron)
    --poll SECONDS     Override polling interval
    --resume-only      Recover interrupted jobs but do not start new ones

Exit codes: 0 OK, 1 error, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
import uuid
from pathlib import Path

# Make project root importable regardless of CWD
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config import Config, ConfigError, load_config
from core.db import Database
from core.logger import get_logger, setup_logging
from core.queue import (
    QueueEngine, WORKING_STAGES,
)

log = get_logger("main")

# ---------------------------------------------------------------------------
# Worker import hook — Agent 02/03 modules register themselves at import time.
# ---------------------------------------------------------------------------

def _try_load_workers() -> None:
    """Import module workers for each pipeline stage if they exist."""
    for stage in sorted(WORKING_STAGES):
        module_name = {
            "DOWNLOADING": "modules.downloader",
            "TRANSCRIBING": "modules.transcriber",
            "ANALYZING": "modules.analyzer",
            "CLIPPING": "modules.clipper",
            "CAPTIONING": "modules.captioner",
            "METADATA": "modules.metadata",
        }[stage]
        try:
            __import__(module_name)
        except ImportError as exc:
            log.debug("stage %s worker unavailable: %s", stage, exc)
        except Exception as exc:  # a registered-worker ImportError, not a missing file
            log.warning("stage %s worker failed to load: %s", stage, exc)


# ---------------------------------------------------------------------------
# CLI actions
# ---------------------------------------------------------------------------

def cmd_init(cfg: Config, db: Database, args) -> int:
    db.init_schema()
    print(f"clipit> schema ready at {cfg.resolved_db_path}")
    return 0


def _validate_sources(args) -> list[str]:
    sources = list(args.source) if args.source else []
    return sources


def cmd_add_account(cfg: Config, db: Database, args) -> int:
    if not args.account or not args.niche:
        print("clipit> error: --account/--name and --niche are required to add an account")
        return 2
    account_id = str(uuid.uuid4())[:8]
    sources = _validate_sources(args)
    branding = {}
    metadata = {}
    if args.branding:
        try:
            branding = json.loads(args.branding)
        except json.JSONDecodeError:
            print("clipit> error: --branding must be valid JSON"); return 2
    if args.metadata:
        try:
            metadata = json.loads(args.metadata)
        except json.JSONDecodeError:
            print("clipit> error: --metadata must be valid JSON"); return 2
    db.create_account(
        account_id=account_id, name=args.account, niche=args.niche, sources=sources,
        branding_preset=branding, metadata_preset=metadata,
        max_daily_clips=args.max_daily or cfg.max_daily_clips_per_account,
    )
    print(f"clipit> account created: {args.account} (id={account_id}) niches={args.niche} sources={len(sources)}")
    return 0


def _resolve_account(db: Database, ref: str) -> Optional[Any]:
    """Resolve an account reference (id or name) to its row, or None."""
    row = db.get_account(ref)
    if row is not None:
        return row
    for acc in db.list_accounts():
        if acc["name"] == ref:
            return acc
    return None


def cmd_add_url(cfg: Config, db: Database, args) -> int:
    if not args.url:
        print("clipit> error: --url is required"); return 2
    # Resolve account: flag (id or name) or first enabled account.
    if args.account and args.account.lower() != "auto":
        account = _resolve_account(db, args.account)
        if account is None:
            print(f"clipit> error: unknown account '{args.account}'"); return 2
        account_id = account["id"]
    else:
        accounts = db.list_accounts(enabled_only=True)
        if not accounts:
            print("clipit> error: no enabled accounts. Add one with --add-account first.")
            return 2
        account_id = accounts[0]["id"]

    source_type = args.source_type or "youtube"
    engine = QueueEngine(db)
    job_id = engine.enqueue(account_id=account_id, source_url=args.url, source_type=source_type)
    print(f"clipit> enqueued job {job_id} [{source_type}] -> account {account_id}")
    return 0


def cmd_list(cfg: Config, db: Database, args) -> int:
    engine = QueueEngine(db)
    print(f"clipit> db: {cfg.resolved_db_path}")
    print("\nclipit> accounts:")
    for acc in db.list_accounts():
        sources = db.account_sources(acc["id"])
        print(f"  {acc['id']}  {acc['name']:<22} niche={acc['niche']:<18} "
              f"sources={len(sources):<3} max_clips={acc['max_daily_clips']} "
              f"enabled={bool(acc['enabled'])}")

    print("\nclipit> jobs:")
    counts: dict[str, int] = {}
    for job in db.list_jobs():
        counts[job["status"]] = counts.get(job["status"], 0) + 1
        print(f"  {job['id']}  {job['status']:<12} {job['source_type']:<10} "
              f"{job['account_id']:<8} retry={job['retry_count']}/{job['max_retries']} "
              f"{(job['title'] or job['source_url'])[:45]}")
    if counts:
        print("\nclipit> summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    else:
        print("\nclipit> summary: no jobs yet")

    clips = db.list_clips()
    if clips:
        print(f"\nclipit> clips ({len(clips)}):")
        for c in clips:
            print(f"  {c['id']}  job={c['job_id']}  score={c['virality_score']:.2f}  "
                  f"approved={c['approved']}  [{c['start_time']}..{c['end_time']}]  {c['title'] or ''}")
    return 0


def cmd_resume(cfg: Config, db: Database, args) -> int:
    engine = QueueEngine(db)
    resumed = engine.recover()
    print(f"clipit> recovery: resumed {len(resumed)} interrupted job(s): {resumed if resumed else 'none'}")
    return 0


# ---------------------------------------------------------------------------
# Daemon supervisor
# ---------------------------------------------------------------------------

class Daemon:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self.engine = QueueEngine(db)
        self._stop = False

    def _install_signal_handlers(self) -> None:
        def handler(*_):
            log.info("shutdown signal received")
            self._stop = True
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def run_once(self) -> int:
        """Single scheduler tick (used for --once, cron, tests)."""
        self.engine.recover()
        picked = self.engine.round_robin_cycle()
        for account_id, job in picked:
            try:
                final = self.engine.run_job(job)
                log.info("tick: job %s finished stage %s", job["id"], final)
            except Exception as exc:
                log.exception("tick: job %s crashed", job["id"])
        self.db.log_event("INFO", "daemon tick complete",
                          data={"dispatched": len(picked)})
        return 0

    def run_loop(self) -> int:
        poll_secs = self.cfg.polling_interval_seconds
        log.info("daemon starting — recover then poll every %ss", poll_secs)
        recovered = self.engine.recover()
        if recovered:
            log.info("recovered %s interrupted job(s)", len(recovered))
        while not self._stop:
            try:
                self.run_once()
            except Exception as exc:
                log.exception("daemon tick error")
            time.sleep(poll_secs)
        log.info("daemon stopped cleanly")
        return 0


def cmd_daemon(cfg, db, args) -> int:
    if getattr(args, "poll", 0):
        cfg.polling_interval_seconds = args.poll
    _try_load_workers()
    daemon = Daemon(cfg, db)
    if args.once:
        return daemon.run_once()
    daemon._install_signal_handlers()
    return daemon.run_loop()


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="clipit", description="ClipIt core daemon & CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--config", help="Path to config.json (default: <root>/config.json)")
    p.add_argument("--db", help="Override database path")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Create/upgrade DB schema")

    p_acct = sub.add_parser("add-account", help="register a content account")
    p_acct.add_argument("--name", "--account", dest="account", required=True)
    p_acct.add_argument("--niche", required=True)
    p_acct.add_argument("--source", action="append", default=[],
                        help="source URL (repeatable)")
    p_acct.add_argument("--branding", help="branding preset as JSON")
    p_acct.add_argument("--metadata", help="metadata preset as JSON")
    p_acct.add_argument("--max-daily", type=int, default=0,
                        help="max clips per day (0 = use config default)")

    p_url = sub.add_parser("add-url", help="queue a video/folder for processing")
    p_url.add_argument("url")
    p_url.add_argument("--account", help="target account id (default: first enabled)")
    p_url.add_argument("--source-type", choices=["youtube", "local_file"], default="youtube")

    sub.add_parser("list", help="show accounts, jobs and clips")
    sub.add_parser("resume", help="recover interrupted jobs")

    p_daemon = sub.add_parser("daemon", help="run the background supervisor")
    p_daemon.add_argument("--once", action="store_true",
                          help="process a single tick and exit")
    p_daemon.add_argument("--poll", type=int, default=0,
                          help="override polling interval (seconds)")
    p_daemon.add_argument("--workers", action="store_true",
                          help="attempt to load stage worker modules")

    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(level=args.log_level)

    # Load config (daemon requires API keys; CLI utility commands tolerate missing keys)
    require_keys = args.cmd == "daemon"
    try:
        cfg = load_config(config_path=args.config, require_api_keys=require_keys)
    except ConfigError as exc:
        print(f"clipit> config error: {exc}", file=sys.stderr)
        return 1

    if args.db:
        # Allow explicit DB override; bypass the path-traversal check's default root.
        cfg.resolved_db_path = Path(args.db).resolve()

    db = Database(cfg.resolved_db_path)

    if args.cmd == "init":
        return cmd_init(cfg, db, args)
    if args.cmd == "add-account":
        return cmd_add_account(cfg, db, args)
    if args.cmd == "add-url":
        return cmd_add_url(cfg, db, args)
    if args.cmd == "list":
        return cmd_list(cfg, db, args)
    if args.cmd == "resume":
        return cmd_resume(cfg, db, args)
    if args.cmd == "daemon":
        return cmd_daemon(cfg, db, args)
    print("clipit> error: unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())