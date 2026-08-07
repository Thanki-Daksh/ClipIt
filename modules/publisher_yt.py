"""
modules/publisher_yt.py — YouTube Shorts Auto-Poster (Agent 05)
===============================================================
Uploads approved clips to YouTube Shorts via the YouTube Data API v3
(resumable media upload).

Owned by Agent 05 (Mobile Daemon & OS Runtime) per TSK-A05-09. The
pipeline's terminal stage is METADATA -> COMPLETED, so publishing is a
standalone step that runs AFTER the pipeline — triggered from the CLI, a
UI approval hook, or a scheduler guard that consults the monitor's pause
state (scripts/termux_monitor.py wipes MONITOR.paused).

Auth — YouTube Data API v3 REQUIRES OAuth 2.0 (an API *key* cannot upload).
Provide either a short-lived access token or a refresh-token trio:

  YOUTUBE_ACCESS_TOKEN       OAuth access token (if you already refresh one)
  YOUTUBE_REFRESH_TOKEN      + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET
  YOUTUBE_PRIVACY            public | unlisted | private (default public)
  YOUTUBE_CATEGORY_ID        default 22 (People & Blogs)

Security: no network at import; HTTP is injected so tests can stub it.
--dry-run builds/validates everything but never contacts the API.

Usage:
    python -m modules.publisher_yt --list
    python -m modules.publisher_yt --clip-id <id> --publish
    python -m modules.publisher_yt --publish-all --dry-run
    python -m modules.publisher_yt --verify-config
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger("publisher_yt")

UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_PRIVACY = "public"
DEFAULT_CATEGORY = "22"  # People & Blogs


def _http_adapter():
    """Lazy 'requests'-backed adapter so importing needs no network deps."""
    try:
        import requests
    except Exception:
        return None
    return requests


class PublisherConfigError(Exception):
    """Raised when YouTube secrets are missing/invalid."""


class YouTubePublisher:
    """Uploads approved clips to YouTube Shorts via Data API v3."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        privacy: Optional[str] = None,
        category_id: Any = None,
        http: Any = None,
    ) -> None:
        self.access_token = access_token or ""
        self.refresh_token = refresh_token or ""
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.privacy = privacy or DEFAULT_PRIVACY
        self.category_id = category_id or DEFAULT_CATEGORY
        self.http = http

    # -- auth ----------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.access_token or (self.refresh_token and self.client_id and self.client_secret))

    def missing(self) -> list[str]:
        if not self.configured():
            return ["YOUTUBE_ACCESS_TOKEN OR (YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET)"]
        return []

    def _bearer(self) -> str:
        if self.access_token:
            return self.access_token
        if not (self.refresh_token and self.client_id and self.client_secret):
            self._no_auth()
        if self.http is None:
            raise PublisherConfigError("No HTTP transport available for token refresh")
        resp = self.http.post(
            TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        data = resp.json()
        if "access_token" not in data:
            raise PublisherConfigError(
                f"Token refresh failed: {data.get('error', resp.status_code)}"
            )
        return str(data["access_token"])

    def _no_auth(self) -> None:
        raise PublisherConfigError(
            "YouTube not configured: set YOUTUBE_ACCESS_TOKEN or "
            "YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET"
        )

    # -- upload --------------------------------------------------------
    def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        hashtags: Optional[list[str]] = None,
    ) -> dict:
        """Upload one video as a YouTube Short. Returns {ok, video_id, url}."""
        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"video not found: {video_path}")
        if not self.configured():
            self._no_auth()
        if self.http is None:
            raise PublisherConfigError("No HTTP layer available for upload")

        token = self._bearer()
        tags = self._normalize_tags(hashtags)
        snippet = {
            "title": str(title)[:100],
            "description": self._join_description(description, tags),
            "categoryId": str(self.category_id),
        }
        if tags:
            snippet["tags"] = tags
        payload = {
            "snippet": snippet,
            "status": {
                "privacyStatus": self.privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        # 1) Create resumable session.
        init = self.http.post(
            UPLOAD_API,
            params={"uploadType": "resumable"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(os.path.getsize(video_path)),
            },
            data=json.dumps(payload),
            timeout=30,
        )
        if init.status_code not in (200, 201):
            raise PublisherConfigError(
                f"Upload init failed: {init.status_code} {init.text[:300]}"
            )
        location = init.headers.get("Location")
        if not location:
            raise PublisherConfigError("Upload init returned no Location URL")

        # 2) Stream file body.
        with open(video_path, "rb") as fh:
            body = fh.read()
        up = self.http.put(
            location,
            headers={"Content-Type": "video/*", "Content-Length": str(len(body))},
            data=body,
            timeout=900,
        )
        if up.status_code not in (200, 201):
            raise PublisherConfigError(f"Upload body failed: {up.status_code} {up.text[:300]}")
        data = up.json()
        video_id = data.get("id")
        logger.info("YouTube short uploaded: id=%s", video_id)
        return {
            "ok": True,
            "video_id": video_id,
            "url": f"https://youtu.be/{video_id}",
        }

    # -- helpers -------------------------------------------------------
    @staticmethod
    def _normalize_tags(hashtags: Optional[list[str]]) -> list[str]:
        """Clean tags but KEEP the leading '#' (YouTube expects '#'-prefixed)."""
        if not hashtags:
            return []
        clean: list[str] = []
        for t in hashtags:
            t = str(t).strip().replace(" ", "_")
            if not t:
                continue
            if not t.startswith("#"):
                t = f"#{t}"
            clean.append(t)
        return clean

    @staticmethod
    def _join_description(description: str, tags: list[str]) -> str:
        body = (description or "").strip()
        tag_str = " ".join(tags) if tags else "#shorts"
        return "\n".join(p for p in (body, tag_str) if p)


# ---------------------------------------------------------------------------
# Approved-clip discovery (read-only SQLite — never mutates pipeline state)
# ---------------------------------------------------------------------------
def find_approved_clips(db_path: str, approved_only: bool = True) -> list[dict]:
    import sqlite3

    if not os.path.isfile(db_path):
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # Core pipeline schema has 'approved' (int flag); the older UI/seed schema
    # has 'status' instead. Introspect so we never hard-crash on either.
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
        "access_token": os.environ.get("YOUTUBE_ACCESS_TOKEN", ""),
        "refresh_token": os.environ.get("YOUTUBE_REFRESH_TOKEN", ""),
        "client_id": os.environ.get("YOUTUBE_CLIENT_ID", ""),
        "client_secret": os.environ.get("YOUTUBE_CLIENT_SECRET", ""),
        "privacy": os.environ.get("YOUTUBE_PRIVACY", DEFAULT_PRIVACY),
        "category_id": os.environ.get("YOUTUBE_CATEGORY_ID", DEFAULT_CATEGORY),
    }


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="publisher_yt", description="YouTube Shorts auto-poster (Agent 05)")
    p.add_argument("--db", default=os.environ.get("CLIPIT_DATABASE_PATH", "storage/clipit.db"))
    p.add_argument("--list", action="store_true", help="list approved clips")
    p.add_argument("--publish-all", action="store_true", help="publish all approved clips")
    p.add_argument("--clip-id", help="publish one clip by id")
    p.add_argument("--dry-run", action="store_true", help="validate without network")
    p.add_argument("--verify-config", action="store_true", help="show which secrets exist (no values)")
    args = p.parse_args(argv)

    if args.verify_config:
        pub = YouTubePublisher(**_env_config())
        missing = pub.missing()
        present = "configured" if not missing else f"missing: {', '.join(missing)}"
        print(f"publisher_yt> {present} (privacy={pub.privacy}, category={pub.category_id})")
        return 0 if not missing else 1

    if args.list:
        rows = find_approved_clips(args.db)
        if not rows:
            print("publisher_yt> no approved clips with a rendered video yet.")
            return 0
        for r in rows:
            print(f"  {r['id']}  score={float(r.get('virality_score') or 0):.1f}  "
                  f"{(r.get('title') or r['id'])[:40]}  -> {r.get('video_path')}")
        return 0

    pub = YouTubePublisher(**_env_config())
    if not pub.configured() and not args.dry_run:
        print("publisher_yt> ERROR: YouTube not configured. Run --verify-config.")
        return 1

    clips = find_approved_clips(args.db)
    if args.clip_id:
        clips = [c for c in clips if c["id"] == args.clip_id]
    if not clips:
        print("publisher_yt> no approved clips to publish.")
        return 0

    ok = 0
    for clip in clips:
        path = clip.get("video_path")
        if args.dry_run:
            print(f"publisher_yt> [DRY] would publish {clip['id']}: "
                  f"'{str(clip.get('title') or clip['id'])[:60]}' ({path})")
            ok += 1
            continue
        if not path or not os.path.isfile(path):
            print(f"publisher_yt> skip {clip['id']}: video file missing ({path})")
            continue
        title = clip.get("title") or f"Clip {clip['id']}"
        desc = clip.get("description") or ""
        raw_tags = clip.get("hashtags") or ""
        tags = raw_tags.split() if isinstance(raw_tags, str) else list(raw_tags or [])
        try:
            res = pub.publish(path, title=title, description=desc, hashtags=tags)
            print(f"publisher_yt> uploaded {clip['id']} -> {res['url']}")
            ok += 1
        except PublisherConfigError as exc:
            print(f"publisher_yt> ERROR {clip['id']}: {exc}")
    return 0 if (args.dry_run or ok) else 1


if __name__ == "__main__":
    sys.exit(main())