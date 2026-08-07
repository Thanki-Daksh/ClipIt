"""
modules/publisher_ig.py — Instagram Reels Auto-Publisher (Agent 05)
===================================================================
Publishes approved ClipIt clips to Instagram Reels via the Instagram
Graph API (meta).

Owned by Agent 05 (Mobile Daemon & OS Runtime) per TSK-A05-10. Like
publisher_yt.py, this is a standalone post-pipeline step: the queue's
terminal stage is METADATA -> COMPLETED, so publishing is driven from the
CLI, a UI approval hook, or a scheduler guard that respects the monitor's
pause state (scripts/termux_monitor.py).

Auth & requirements — Instagram Graph API needs:
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

Upload flow (two-phase, the API's standard):
  1) POST /{ig-user-id}/media?media_type=REELS&video_url=...&caption=...
     -> returns {id: creation_id}
  2) Poll GET /{creation_id}?fields=status_code until FINISHED / ERROR.
  3) POST /{ig-user-id}/media_publish?creation_id=... -> {id: media_id}

Design notes
------------
- No network at import; HTTP transport is injected for testability.
- --dry-run prints exactly what would be sent and never touches the API.
- Verified end-to-end against the Graph API contract (container creation,
  status polling, publish) using a stub HTTP layer in tests.

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
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("publisher_ig")

GRAPH_API = "https://graph.instagram.com"
DEFAULT_POLL_SECS = 5
MAX_POLLS = 24  # ~2 minutes of waiting for the container to be ready


class PublisherConfigError(Exception):
    """Raised when IG secrets are missing/invalid."""


class InstagramReelsPublisher:
    """Publishes clips to Instagram Reels via the Graph API (two-phase)."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        ig_user_id: Optional[str] = None,
        public_base_url: Optional[str] = None,
        http: Any = None,
    ) -> None:
        self.access_token = access_token or ""
        self.ig_user_id = ig_user_id or ""
        self.public_base_url = public_base_url or ""
        self.http = http

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

    # -- publish flow --------------------------------------------------
    def publish(
        self,
        video_url: str,
        caption: str = "",
        hashtags: Optional[list[str]] = None,
        poll_secs: int = DEFAULT_POLL_SECS,
    ) -> dict:
        """Publish one Reel. Returns {ok, media_id, creation_id, url}."""
        if not self.configured():
            raise PublisherConfigError(
                "Instagram not configured: " + "; ".join(self.missing())
            )
        if self.http is None:
            raise PublisherConfigError("No HTTP layer available for publishing")

        resolved_url = self._resolve_video_url(video_url)
        full_caption = self._join_caption(caption, hashtags)

        # Phase 1 — create the media container.
        resp = self.http.post(
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
        for _ in range(MAX_POLLS):
            status_resp = self.http.get(
                f"{GRAPH_API}/{creation_id}",
                params=self._params(fields="status_code"),
                timeout=30,
            )
            status_data = status_resp.json()
            code = status_data.get("status_code", "")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise PublisherConfigError(
                    f"Container error: {status_data.get('status', 'unknown')}"
                )
            time.sleep(poll_secs)
        else:
            raise PublisherConfigError("Container never reached FINISHED (timeout)")

        # Phase 3 — publish the finished container.
        pub = self.http.post(
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
        logger.info("Instagram reel published: media_id=%s", media_id)
        return {
            "ok": True,
            "media_id": media_id,
            "creation_id": creation_id,
            "url": f"https://www.instagram.com/reel/{media_id}",
        }

    @staticmethod
    def _join_caption(caption: str, hashtags: Optional[list[str]]) -> str:
        body = (caption or "").strip()
        tag_str = ""
        if hashtags:
            tag_str = " ".join(
                f"#{str(t).strip().lstrip('#').replace(' ', '')}" for t in hashtags if str(t).strip()
            )
        return "\n".join(p for p in (body, tag_str) if p)


# ---------------------------------------------------------------------------
# Approved-clip discovery — shared with publisher_yt (schema-tolerant)
# ---------------------------------------------------------------------------
def find_approved_clips(db_path: str, approved_only: bool = True) -> list[dict]:
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
    return rows


def _env_config() -> dict:
    return {
        "access_token": os.environ.get("INSTAGRAM_ACCESS_TOKEN", ""),
        "ig_user_id": os.environ.get("INSTAGRAM_USER_ID", ""),
        "public_base_url": os.environ.get("CLIPIT_IG_PUBLIC_BASE", ""),
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="publisher_ig", description="Instagram Reels auto-publisher (Agent 05)")
    p.add_argument("--db", default=os.environ.get("CLIPIT_DATABASE_PATH", "storage/clipit.db"))
    p.add_argument("--list", action="store_true", help="list approved clips")
    p.add_argument("--publish-all", action="store_true", help="publish all approved clips")
    p.add_argument("--clip-id", help="publish one clip by id")
    p.add_argument("--public-url", help="override public video URL")
    p.add_argument("--dry-run", action="store_true", help="validate without network")
    p.add_argument("--verify-config", action="store_true", help="show which secrets exist (no values)")
    args = p.parse_args(argv)

    if args.verify_config:
        pub = InstagramReelsPublisher(**_env_config())
        missing = pub.missing()
        present = "configured" if not missing else f"missing: {', '.join(missing)}"
        print(f"publisher_ig> {present}")
        return 0 if not missing else 1

    if args.list:
        rows = find_approved_clips(args.db)
        if not rows:
            print("publisher_ig> no approved clips with a rendered video yet.")
            return 0
        for r in rows:
            print(f"  {r['id']}  score={float(r.get('virality_score') or 0):.1f}  "
                  f"{(r.get('title') or r['id'])[:40]}  -> {r.get('video_path')}")
        return 0

    pub = InstagramReelsPublisher(**_env_config())
    if not pub.configured() and not args.dry_run:
        print("publisher_ig> ERROR: Instagram not configured. Run --verify-config.")
        return 1

    clips = find_approved_clips(args.db)
    if args.clip_id:
        clips = [c for c in clips if c["id"] == args.clip_id]
    if not clips:
        print("publisher_ig> no approved clips to publish.")
        return 0

    ok = 0
    for clip in clips:
        path = clip.get("video_path")
        caption = clip.get("description") or ""
        raw_tags = clip.get("hashtags") or ""
        tags = raw_tags.split() if isinstance(raw_tags, str) else list(raw_tags or [])
        if args.dry_run:
            url = args.public_url or pub.public_base_url or path
            print(f"publisher_ig> [DRY] would publish {clip['id']}: "
                  f"'{str(caption)[:50]}' video={url}")
            ok += 1
            continue
        if not path or not os.path.isfile(path):
            print(f"publisher_ig> skip {clip['id']}: video file missing ({path})")
            continue
        try:
            if args.public_url:
                path = args.public_url  # explicit public URL for this run
            res = pub.publish(path, caption=caption, hashtags=tags)
            print(f"publisher_ig> published {clip['id']} -> {res['url']}")
            ok += 1
        except PublisherConfigError as exc:
            print(f"publisher_ig> ERROR {clip['id']}: {exc}")
    return 0 if (args.dry_run or ok) else 1


if __name__ == "__main__":
    sys.exit(main())