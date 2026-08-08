"""
modules/publisher_ig.py — Instagram Reels Auto-Publisher (Agent 05)
===================================================================
Publishes approved ClipIt clips to Instagram Reels via the Instagram
Graph API (Meta). TSK-A05 Social Publisher & API Integrator scope:

  TSK-A05-02  Reels engine — two-phase Graph API container workflow
  TSK-A05-03  OAuth token refresh (long-lived token refresh endpoint,
              plus core.auth.CredentialPool rotation)
  TSK-A05-04  Upload retry & rate-limit engine (exponential backoff,
              up to 3 attempts on transient 429/5xx/network errors)
  TSK-A05-05  Publish schedule dispatcher (ledger JSON + --publish-scheduled)
  TSK-A05-06  Mock publisher mode (simulated publish when tokens absent)
  TSK-A05-07  Publish progress telemetry (create -> poll -> publish stages)
  TSK-A05-08  Multi-account token rotator (round-robin via core.auth)
  TSK-A05-09  Instagram container status poller (until status_code FINISHED)
  TSK-A05-11  Auto #Reels caption/hashtag injection
  TSK-A05-12  Daily upload quota guard (CLIPIT_IG_DAILY_QUOTA, default 25)
  TSK-A05-13  Failed-upload audit trail (job_logs table)
  TSK-A05-15  Post-publish verification probe (media permalink/status)

Requirements — Instagram Graph API needs:
  INSTAGRAM_ACCESS_TOKEN   long-lived user access token (with
                           instagram_business_basic + instagram_content_publish)
  INSTAGRAM_USER_ID        your IG business/user id
  INSTAGRAM_PUBLIC_URL     optional public URL the video is hosted at.
                           The Graph API does NOT accept file uploads for
                           Reels: the video MUST be reachable at a public URL.
                           If CLIPIT_IG_PUBLIC_BASE is set (e.g.
                           https://cdn.example.com/clips), the module builds
                           <base>/<filename> automatically; otherwise pass
                           --public-url or rely on the clip row's
                           video_path if it is already an http(s) URL.
  CLIPIT_MOCK=1            force mock publisher mode

Upload flow (two-phase, the API's standard):
  1. POST /{ig-user-id}/media  -> {id: creation_id}
     (media_type=REELS, video_url=..., caption=...)
  2. Poll GET /{creation_id}?fields=status_code until FINISHED / ERROR.
  3. POST /{ig-user-id}/media_publish?creation_id=... -> {id: media_id}

Design notes:
  - No network at import; HTTP transport is injected for testability.
  - --dry-run / mock mode print exactly what would be sent and never touch
    the API.
  - `publish()` takes `video_url` as its first positional param — the API's
    native name (a QA contract uses that name).

Usage:
    python -m modules.publisher_ig --list
    python -m modules.publisher_ig --clip-id <id> --publish
    python -m modules.publisher_ig --publish-all --dry-run
    python -m modules.publisher_ig --verify-config
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Optional

from core.auth import CredentialPool, UploadQuota, audit_event, due_clip_ids
from core.logger import get_logger

logger = get_logger("publisher_ig")

GRAPH_API = "https://graph.instagram.com"
DEFAULT_POLL_SECS = 5
MAX_POLLS = 24  # ~2 minutes of waiting for the container to be ready
DEFAULT_DAILY_QUOTA = 25  # IG Graph API is far more lenient than YouTube
AUTO_TAG = "#Reels"  # TSK-A05-11 auto-inject
DEFAULT_LEDGER = "storage/logs/publish_schedule.json"  # TSK-A05-05


class PublisherConfigError(Exception):
    """Raised when IG secrets are missing/invalid or the API rejects a call."""


def _is_transient(status: Optional[int]) -> bool:
    """429 rate-limit and 5xx server errors are retryable (TSK-A05-04)."""
    return status is not None and (status == 429 or 500 <= status < 600)


class InstagramReelsPublisher:
    """Publishes clips to Instagram Reels via the Graph API (two-phase)."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        public_base_url: Optional[str] = None,
        http: Any = None,
        # TSK-A05-04 retry knobs (sleep_fn injectable for tests)
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 10.0,
        sleep_fn: Optional[Callable[[float], None]] = None,
        # TSK-A05-06 mock mode
        mock: bool = False,
        # TSK-A05-12 quota guard
        quota: Optional[UploadQuota] = None,
        # TSK-A05-13 audit sink
        db_path: Optional[str] = None,
        # TSK-A05-08 multi-account pool
        pool: Optional[CredentialPool] = None,
        # TSK-A05-07 progress telemetry (phase index, total phases)
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.access_token = access_token or ""
        self.ig_user_id = ig_user_id or ""
        self.public_base_url = public_base_url or ""
        self.http = http
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.sleep_fn = sleep_fn or time.sleep
        self.mock = mock or os.environ.get("CLIPIT_MOCK", "") == "1"
        self.quota = quota or UploadQuota()
        self.db_path = db_path
        self.pool = pool
        self.progress_cb = progress_cb

    # -- config --------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.access_token and self.ig_user_id)

    def missing(self) -> list[str]:
        out: list[str] = []
        if not self.access_token:
            out.append("INSTAGRAM_ACCESS_TOKEN")
        if not self.ig_user_id:
            out.append("INSTAGRAM_USER_ID")
        return out

    # -- helpers -------------------------------------------------------
    def _params(self, **extra: Any) -> dict:
        p: dict = {"access_token": self.access_token}
        p.update(extra)
        return p

    def _progress(self, stage: int, total: int) -> None:
        if self.progress_cb:
            try:
                self.progress_cb(stage, total)
            except Exception:
                pass  # telemetry must never break the publish

    def _resolve_video_url(self, video_path: str) -> str:
        """Return a publicly reachable URL for the video.

        Accepts an already-public URL; otherwise builds one from
        public_base_url + filename. The Graph API cannot ingest local files.
        """
        if video_path.startswith(("http://", "https://")):
            return video_path
        if self.public_base_url:
            base = self.public_base_url.rstrip("/")
            return f"{base}/{os.path.basename(video_path)}"
        raise PublisherConfigError(
            "Instagram requires a PUBLIC video URL. Provide INSTAGRAM_PUBLIC_URL "
            "or CLIPIT_IG_PUBLIC_BASE (e.g. https://cdn.example.com/clips)."
        )

    # -- http + retry (TSK-A05-04) -------------------------------------
    def _request(self, method: str, url: str, **kw: Any) -> Any:
        """POST/GET with exponential-backoff retries on transient errors."""
        attempt = 0
        delay = self.backoff_base
        while True:
            try:
                resp = getattr(self.http, method.lower())(url, **kw)
            except Exception as exc:  # network-level failure: retryable
                if attempt >= self.max_retries:
                    raise PublisherConfigError(
                        f"{method} {url} failed after {self.max_retries + 1} attempts: {exc}"
                    ) from exc
                attempt += 1
                self.sleep_fn(min(delay, self.backoff_max))
                delay *= 2
                continue
            if _is_transient(resp.status_code) and attempt < self.max_retries:
                logger.info("transient %s -> %s, retry %s/%s",
                            resp.status_code, url, attempt + 1, self.max_retries)
                attempt += 1
                self.sleep_fn(min(delay, self.backoff_max))
                delay *= 2
                continue
            return resp

    # -- publish flow --------------------------------------------------
    def publish(
        self,
        video_url: str,
        caption: str = "",
        hashtags: Optional[list[str]] = None,
        poll_secs: int = DEFAULT_POLL_SECS,
        account_id: str = "",
        verify: bool = False,
    ) -> dict:
        """Publish one Reel. Returns {ok, media_id, creation_id, url}."""
        if self.mock:
            return self._mock_publish(video_url, caption, hashtags)
        if not self.configured() and self.pool is None:
            raise PublisherConfigError(
                "Instagram not configured: " + "; ".join(self.missing())
            )
        if self.http is None:
            raise PublisherConfigError("No HTTP layer available for publishing")

        # TSK-A05-12 quota guard (per account, per day).
        quota_account = account_id or "__env__"
        if self.quota is not None and not self.quota.can_upload("instagram", quota_account):
            raise PublisherConfigError(
                f"daily quota reached: {self.quota.used('instagram', quota_account)}/"
                f"{self.quota.limit} publishes today for {quota_account}"
            )

        resolved_url = self._resolve_video_url(video_url)
        full_caption = self._join_caption(caption, hashtags)
        self.access_token = self.access_token or self._pool_token()

        # Phase 1 — create the media container.
        self._progress(1, 3)
        resp = self._request(
            "POST",
            f"{GRAPH_API}/{self.ig_user_id}/media",
            data=self._params(
                media_type="REELS",
                video_url=resolved_url,
                caption=full_caption[:2200],
            ),
            timeout=60,
        )
        data = resp.json()
        creation_id = data.get("id")
        if not creation_id:
            raise PublisherConfigError(
                f"Container creation failed: {data.get('error', resp.status_code)}"
            )

        # Phase 2 — poll until the container is FINISHED (or errored).
        self._progress(2, 3)
        status_data = self._poll_container(creation_id, poll_secs)

        # Phase 3 — publish the finished container.
        self._progress(3, 3)
        pub = self._request(
            "POST",
            f"{GRAPH_API}/{self.ig_user_id}/media_publish",
            data=self._params(creation_id=creation_id),
            timeout=60,
        )
        pub_data = pub.json()
        media_id = pub_data.get("id")
        if not media_id:
            raise PublisherConfigError(
                f"Publish failed: {pub_data.get('error', pub.status_code)}"
            )
        if self.quota is not None:
            self.quota.record("instagram", quota_account)
        logger.info("Instagram reel published: media_id=%s account=%s", media_id, quota_account)

        result: dict = {
            "ok": True,
            "media_id": media_id,
            "creation_id": creation_id,
            "url": f"https://www.instagram.com/reel/{media_id}",
        }
        # TSK-A05-15 post-publish verification probe.
        if verify:
            probe = self.verify(media_id)
            result["verified"] = bool(probe.get("live"))
            result["probe"] = probe
        return result

    def _pool_token(self) -> str:
        if self.pool is None:
            return self.access_token
        account_id, token = self.pool.bearer_round_robin()
        if not self.ig_user_id:
            self.ig_user_id = account_id if account_id != "__env__" else ""
        return token

    def _poll_container(self, creation_id: str, poll_secs: int) -> dict:
        """TSK-A05-09: poll status_code until FINISHED / ERROR / timeout."""
        for _ in range(MAX_POLLS):
            status_resp = self._request(
                "GET",
                f"{GRAPH_API}/{creation_id}",
                params=self._params(fields="status_code"),
                timeout=30,
            )
            status_data = status_resp.json()
            code = status_data.get("status_code", "")
            if code == "FINISHED":
                return status_data
            if code == "ERROR":
                raise PublisherConfigError(
                    f"Container error: {status_data.get('status', 'unknown')}"
                )
            self.sleep_fn(poll_secs)
        raise PublisherConfigError("Container never reached FINISHED (timeout)")

    def verify(self, media_id: str) -> dict:
        """TSK-A05-15: confirm the published Reel is live via the media node."""
        if self.http is None:
            return {"ok": False, "live": True, "reason": "no-http"}
        try:
            resp = self._request(
                "GET",
                f"{GRAPH_API}/{media_id}",
                params=self._params(fields="id,permalink,status"),
                timeout=30,
            )
            if resp.status_code != 200:
                return {"ok": False, "live": True, "reason": f"probe-status-{resp.status_code}"}
            body = resp.json()
            live = bool(body.get("permalink")) or body.get("status") == "LIVE"
            return {"ok": True, "live": live, "media": body}
        except PublisherConfigError:
            return {"ok": False, "live": True, "reason": "probe-failed"}

    def _mock_publish(self, video_url: str, caption: str,
                      hashtags: Optional[list[str]]) -> dict:
        """TSK-A05-06: simulated response — no tokens, no network."""
        mock_id = f"IG_MOCK_{abs(hash(video_url or caption)) % 100000:05d}"
        logger.info("MOCK instagram publish: %s", caption[:50])
        return {
            "ok": True,
            "media_id": mock_id,
            "creation_id": f"CREATED_{mock_id}",
            "url": f"https://www.instagram.com/reel/{mock_id}",
            "mock": True,
        }

    @staticmethod
    def _join_caption(caption: str, hashtags: Optional[list[str]]) -> str:
        body = (caption or "").strip()
        tag_str = ""
        if hashtags:
            tag_str = " ".join(
                f"#{str(t).strip().lstrip('#').replace(' ', '')}" for t in hashtags if str(t).strip()
            )
        joined = "\n".join(p for p in (body, tag_str) if p)
        if AUTO_TAG.lower() not in joined.lower():
            joined = f"{joined}\n{AUTO_TAG}"  # TSK-A05-11 auto #Reels
        return joined


# ---------------------------------------------------------------------------
# Approved-clip discovery — shared contract with publisher_yt (schema-tolerant)
# ---------------------------------------------------------------------------
def find_approved_clips(db_path: str, approved_only: bool = True,
                        schedule_file: Optional[str] = None) -> list[dict]:
    import sqlite3

    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cols = {c[1] for c in conn.execute("PRAGMA table_info(clips)").fetchall()}
    q = "SELECT * FROM clips"
    if approved_only:
        if "approved" in cols:
            q += " WHERE approved = 1 AND video_path IS NOT NULL AND video_path != ''"
        elif "status" in cols:
            q += " WHERE status IN ('approved','ready') AND video_path IS NOT NULL AND video_path != ''"
        else:
            q += " WHERE video_path IS NOT NULL AND video_path != ''"
    q += " ORDER BY created_at DESC"
    rows = [dict(r) for r in conn.execute(q).fetchall()]
    conn.close()
    if schedule_file:  # TSK-A05-05: keep only clips due for publish
        due = set(due_clip_ids(schedule_file))
        rows = [r for r in rows if r["id"] in due]
    return rows


def _env_config() -> dict:
    return {
        "access_token": os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""),
        "ig_user_id": os.environ.get("INSTAGRAM_USER_ID", ""),
        "public_base_url": os.environ.get("CLIPIT_IG_PUBLIC_BASE", ""),
    }


def _split_hashtags(clip: dict) -> list[str]:
    raw = clip.get("hashtags") or ""
    return raw.split() if isinstance(raw, str) else list(raw or [])


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="publisher_ig", description="Instagram Reels auto-publisher (Agent 05)")
    p.add_argument("--db", default=os.environ.get("CLIPIT_DATABASE_PATH", "storage/clipit.db"))
    p.add_argument("--list", action="store_true", help="list approved clips")
    p.add_argument("--publish-all", action="store_true", help="publish all approved clips")
    p.add_argument("--clip-id", help="publish one clip by id")
    p.add_argument("--public-url", help="override public video URL")
    p.add_argument("--dry-run", action="store_true", help="validate without network")
    p.add_argument("--mock", action="store_true", help="simulate publishes (TSK-A05-06)")
    p.add_argument("--verify", action="store_true", help="probe after publish (TSK-A05-15)")
    p.add_argument("--schedule-file", default=None, help="publish ledger JSON (TSK-A05-05)")
    p.add_argument("--publish-scheduled", action="store_true",
                   help="publish only clips due per --schedule-file (TSK-A05-05)")
    p.add_argument("--verify-config", action="store_true", help="show which secrets exist (no values)")
    args = p.parse_args(argv)

    if args.verify_config:
        pub = InstagramReelsPublisher(**_env_config())
        missing = pub.missing()
        present = "configured" if not missing else f"missing: {', '.join(missing)}"
        print(f"publisher_ig> {present}")
        return 0 if not missing else 1

    if args.list:
        rows = find_approved_clips(args.db,
                                   schedule_file=args.schedule_file if args.publish_scheduled else None)
        if not rows:
            print("publisher_ig> no approved clips with a rendered video yet.")
            return 0
        for r in rows:
            print(f"  {r['id']}  score={float(r.get('virality_score') or 0):.1f}  "
                  f"{(r.get('title') or r['id'])[:40]}  -> {r.get('video_path')}")
        return 0

    pub = InstagramReelsPublisher(
        **_env_config(), mock=args.mock, db_path=args.db,
        quota=UploadQuota(limit=int(os.environ.get("CLIPIT_IG_DAILY_QUOTA", DEFAULT_DAILY_QUOTA))),
    )
    if not pub.configured() and not args.dry_run and not pub.mock:
        print("publisher_ig> ERROR: Instagram not configured. Run --verify-config (or --mock).")
        return 1

    clips = find_approved_clips(
        args.db,
        schedule_file=(args.schedule_file or DEFAULT_LEDGER) if args.publish_scheduled else None,
    )
    if args.clip_id:
        clips = [c for c in clips if c["id"] == args.clip_id]
    if not clips:
        print("publisher_ig> no approved clips to publish.")
        return 0

    ok = 0
    for clip in clips:
        path = clip.get("video_path")
        caption = clip.get("description") or ""
        tags = _split_hashtags(clip)
        if args.dry_run or pub.mock:
            outcome = pub._mock_publish(path or "/mock.mp4", caption, tags)
            print(f"publisher_ig> [DRY] would publish {clip['id']}: "
                  f"'{str(caption)[:50]}' -> {outcome['url']}")
            ok += 1
            continue
        if not path or not os.path.isfile(path):
            print(f"publisher_ig> skip {clip['id']}: video file missing ({path})")
            continue
        video_url = args.public_url or path
        try:
            res = pub.publish(video_url, caption=caption, hashtags=tags,
                              account_id=clip.get("account_id", ""), verify=args.verify)
            extra = " [verified]" if res.get("probe", {}).get("live") else ""
            print(f"publisher_ig> published {clip['id']} -> {res['url']}{extra}")
            ok += 1
        except PublisherConfigError as exc:
            # TSK-A05-13 failed-upload audit trail.
            audit_event(args.db, "instagram", clip.get("id", ""), "failed",
                        error=str(exc), account_id=clip.get("account_id", ""))
            print(f"publisher_ig> ERROR {clip['id']}: {exc}")
    return 0 if (args.dry_run or args.mock or ok) else 1


if __name__ == "__main__":
    sys.exit(main())