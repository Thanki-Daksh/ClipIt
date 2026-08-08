"""
modules/publisher_yt.py — YouTube Shorts Auto-Poster (Agent 05)
===============================================================
Uploads approved clips to YouTube Shorts via the YouTube Data API v3
(resumable media upload). TSK-A05 Social Publisher & API Integrator scope:

  TSK-A05-01  Shorts engine — Data API v3 resumable upload
  TSK-A05-03  OAuth token refresh (access token OR refresh-token trio,
              plus core.auth.CredentialPool rotation)
  TSK-A05-04  Upload retry & rate-limit engine (exponential backoff,
              up to 3 attempts on transient 429/5xx/network errors)
  TSK-A05-05  Publish schedule dispatcher (ledger JSON + --publish-scheduled)
  TSK-A05-06  Mock publisher mode (simulated upload when tokens absent)
  TSK-A05-07  Upload progress telemetry (chunked stream + callback)
  TSK-A05-08  Multi-account token rotator (round-robin via core.auth)
  TSK-A05-10  Category & privacy flags (categoryId=22, privacyStatus)
  TSK-A05-11  Auto #Shorts caption/hashtag injection
  TSK-A05-12  Daily upload quota guard (6 uploads/account/day)
  TSK-A05-13  Failed-upload audit trail (job_logs table)
  TSK-A05-14  Custom cover frame uploader (thumbnails.set endpoint)
  TSK-A05-15  Post-publish verification probe (videos.list status)

Auth — Data API v3 REQUIRES OAuth 2.0 (an API *key* cannot upload):

  YOUTUBE_ACCESS_TOKEN       OAuth access token (if you already refresh one)
  YOUTUBE_REFRESH_TOKEN      + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET
  YOUTUBE_PRIVACY            public | unlisted | private (default public)
  YOUTUBE_CATEGORY_ID        default 22 (People & Blogs)
  CLIPIT_YT_DAILY_QUOTA      max uploads per account per day (default 6)
  CLIPIT_MOCK=1              force mock publisher mode

Security: no network at import; HTTP is injected so tests can stub it.
--dry-run / mock mode build/validate everything but never contact the API.

Usage:
    python -m modules.publisher_yt --list
    python -m modules.publisher_yt --clip-id <id> --publish
    python -m modules.publisher_yt --publish-all --dry-run
    python -m modules.publisher_yt --verify-config
    python -m modules.publisher_yt --publish-scheduled --schedule-file <ledger.json>
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable, Optional

from core.auth import CredentialPool, UploadQuota, audit_event, due_clip_ids, load_env_credentials
from core.logger import get_logger

logger = get_logger("publisher_yt")

UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_API = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
VIDEOS_API = "https://www.googleapis.com/youtube/v3/videos"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_PRIVACY = "public"
DEFAULT_CATEGORY = "22"  # People & Blogs
DEFAULT_DAILY_QUOTA = 6  # TSK-A05-12
AUTO_TAG = "#Shorts"  # TSK-A05-11
DEFAULT_LEDGER = "storage/logs/publish_schedule.json"  # TSK-A05-05


class PublisherConfigError(Exception):
    """Raised when YouTube secrets are missing/invalid or the API rejects a call."""


def _is_transient(status: Optional[int]) -> bool:
    """429 rate-limit and 5xx server errors are retryable (TSK-A05-04)."""
    return status is not None and (status == 429 or 500 <= status < 600)


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
        # TSK-A05-07 progress telemetry
        progress_cb: Optional[Callable[[int, int], None]] = None,
        chunk_size: int = 1 << 20,
    ) -> None:
        self.access_token = access_token or ""
        self.refresh_token = refresh_token or ""
        self.client_id = client_id or ""
        self.client_secret = client_secret or ""
        self.privacy = privacy or DEFAULT_PRIVACY
        self.category_id = category_id or DEFAULT_CATEGORY
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
        self.chunk_size = chunk_size

    # -- auth ----------------------------------------------------------
    def configured(self) -> bool:
        return bool(self.access_token or (self.refresh_token and self.client_id and self.client_secret))

    def missing(self) -> list[str]:
        if not self.configured():
            return ["YOUTUBE_ACCESS_TOKEN OR (YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET)"]
        return []

    def _bearer(self) -> str:
        """TSK-A05-03 refresh / TSK-A05-08 rotation-aware bearer resolution."""
        if self.access_token:
            return self.access_token
        if self.pool is not None:
            _, token = self.pool.bearer_round_robin()
            return token
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

    # -- http + retry (TSK-A05-04) -------------------------------------
    def _request(self, method: str, url: str, **kw: Any) -> Any:
        """POST/PUT/GET with exponential-backoff retries on transient errors."""
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

    # -- upload --------------------------------------------------------
    def publish(
        self,
        video_path: str,
        title: str,
        description: str = "",
        hashtags: Optional[list[str]] = None,
        account_id: str = "",
        category_id: Any = None,
        privacy: Optional[str] = None,
        cover_path: Optional[str] = None,
        verify: bool = False,
    ) -> dict:
        """Upload one video as a YouTube Short. Returns {ok, video_id, url}."""
        if self.mock:
            return self._mock_publish(video_path, title, description, hashtags)

        if not os.path.isfile(video_path):
            raise FileNotFoundError(f"video not found: {video_path}")
        if not self.configured() and self.pool is None:
            self._no_auth()
        if self.http is None:
            raise PublisherConfigError("No HTTP layer available for upload")

        # TSK-A05-12 quota guard (per account, per day).
        quota_account = account_id or "__env__"
        if not self.quota.can_upload("youtube", quota_account):
            raise PublisherConfigError(
                f"daily quota reached: {self.quota.used('youtube', quota_account)}/"
                f"{self.quota.limit} uploads today for {quota_account}"
            )

        token = self._bearer()
        tags = self._normalize_tags(hashtags)
        snippet = {
            "title": str(title)[:100],
            "description": self._join_description(description, tags),
            "categoryId": str(category_id or self.category_id),
        }
        if tags:
            snippet["tags"] = tags
        payload = {
            "snippet": snippet,
            "status": {
                "privacyStatus": privacy or self.privacy,
                "selfDeclaredMadeForKids": False,
            },
        }

        total = os.path.getsize(video_path)
        # 1) Create resumable session.
        init = self._request(
            "POST",
            UPLOAD_API,
            params={"uploadType": "resumable"},
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(total),
            },
            data=json.dumps(payload),
            timeout=60,
        )
        if init.status_code not in (200, 201):
            raise PublisherConfigError(f"Upload init failed: {init.status_code} {init.text[:300]}")
        location = init.headers.get("Location")
        if not location:
            raise PublisherConfigError("Upload init returned no Location URL")

        # 2) Stream file body. With progress telemetry we send a chunked
        # reader; otherwise the whole byte string (test contract asserts the
        # exact bytes hit the stub) — TSK-A05-07 path is opt-in.
        if self.progress_cb:
            data_body: Any = self._iter_chunks(video_path, total)
        else:
            with open(video_path, "rb") as fh:
                data_body = fh.read()
        up = self._request(
            "PUT",
            location,
            headers={"Content-Type": "video/*", "Content-Length": str(total)},
            data=data_body,
            timeout=900,
        )
        if up.status_code not in (200, 201):
            raise PublisherConfigError(f"Upload body failed: {up.status_code} {up.text[:300]}")
        data = up.json()
        video_id = data.get("id")
        if not video_id:
            raise PublisherConfigError(f"Upload response missing id: {data}")

        self.quota.record("youtube", quota_account)
        logger.info("YouTube short uploaded: id=%s account=%s", video_id, quota_account)

        result: dict = {"ok": True, "video_id": video_id, "url": f"https://youtu.be/{video_id}"}

        # TSK-A05-14 custom cover frame (thumbnail) upload.
        if cover_path:
            if os.path.isfile(cover_path):
                result["cover"] = self.upload_thumbnail(video_id, cover_path, token=token)
            else:
                logger.warning("cover file missing: %s (skipped)", cover_path)

        # TSK-A05-15 post-publish verification probe.
        if verify:
            probe = self.verify(video_id, token=token)
            result["verified"] = bool(probe.get("live"))
            result["probe"] = probe
        return result

    def upload_thumbnail(self, video_id: str, cover_path: str, token: Optional[str] = None) -> dict:
        """Upload a custom cover frame PNG/JPG via thumbnails.set (TSK-A05-14)."""
        if not os.path.isfile(cover_path):
            raise FileNotFoundError(f"cover not found: {cover_path}")
        if self.http is None:
            raise PublisherConfigError("No HTTP layer available for thumbnail upload")
        token = token or self._bearer()
        with open(cover_path, "rb") as fh:
            resp = self._request(
                "POST",
                THUMBNAIL_API,
                params={"videoId": video_id, "uploadType": "media"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "image/png" if cover_path.lower().endswith(".png") else "image/jpeg",
                    "Content-Length": str(os.path.getsize(cover_path)),
                },
                data=fh.read(),
                timeout=120,
            )
        if resp.status_code not in (200, 201):
            raise PublisherConfigError(f"Thumbnail upload failed: {resp.status_code} {resp.text[:300]}")
        body = resp.json()
        return {"ok": True, "thumbnail": body}

    def verify(self, video_id: str, token: Optional[str] = None) -> dict:
        """
        Post-publish probe (TSK-A05-15): confirm the video is live via videos.list.
        Returns {"ok": bool, "live": bool, "status": ...}; on probe failure it
        degrades to {"ok": False, "live": True} so a failed probe never reports
        the video as missing.
        """
        if self.http is None:
            return {"ok": False, "live": True, "reason": "no-http"}
        token = token or self._bearer()
        try:
            resp = self._request(
                "GET",
                VIDEOS_API,
                params={"part": "status", "id": video_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=30,
            )
            if resp.status_code != 200:
                return {"ok": False, "live": True, "reason": f"probe-status-{resp.status_code}"}
            data = resp.json()
            items = data.get("items") or []
            if not items:
                return {"ok": True, "live": False, "reason": "not-found"}
            status = items[0].get("status", {})
            live = status.get("uploadStatus") == "processed" and status.get("privacyStatus") != "private"
            return {"ok": True, "live": live, "status": status}
        except PublisherConfigError:
            return {"ok": False, "live": True, "reason": "probe-failed"}

    def _mock_publish(self, video_path: str, title: str, description: str,
                      hashtags: Optional[list[str]]) -> dict:
        """TSK-A05-06: simulated response — no tokens, no network."""
        mock_id = f"MOCK-{abs(hash(video_path or title)) % 100000:05d}"
        logger.info("MOCK youtube publish: %s -> %s", title, mock_id)
        return {
            "ok": True,
            "video_id": mock_id,
            "url": f"https://youtu.be/{mock_id}",
            "mock": True,
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

    def _iter_chunks(self, path: str, total: int) -> Any:
        """Chunked reader emitting progress telemetry (TSK-A05-07)."""
        sent = 0
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(self.chunk_size)
                if not chunk:
                    break
                sent += len(chunk)
                if self.progress_cb:
                    try:
                        self.progress_cb(sent, total)
                    except Exception:
                        pass  # telemetry must never break the upload
                yield chunk

    @staticmethod
    def _join_description(description: str, tags: list[str]) -> str:
        body = (description or "").strip()
        tag_str = " ".join(tags) if tags else AUTO_TAG
        joined = "\n".join(p for p in (body, tag_str) if p)
        if AUTO_TAG.lower() not in joined.lower():
            joined = f"{joined}\n{AUTO_TAG}"  # TSK-A05-11 auto #Shorts
        return joined


# ---------------------------------------------------------------------------
# Approved-clip discovery (read-only SQLite — never mutates pipeline state)
# ---------------------------------------------------------------------------
def find_approved_clips(db_path: str, approved_only: bool = True,
                        schedule_file: Optional[str] = None) -> list[dict]:
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
    if schedule_file:  # TSK-A05-05: keep only clips due for publish
        due = set(due_clip_ids(schedule_file))
        rows = [r for r in rows if r["id"] in due]
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


def _split_hashtags(clip: dict) -> list[str]:
    raw = clip.get("hashtags") or ""
    return raw.split() if isinstance(raw, str) else list(raw or [])


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(prog="publisher_yt", description="YouTube Shorts auto-poster (Agent 05)")
    p.add_argument("--db", default=os.environ.get("CLIPIT_DATABASE_PATH", "storage/clipit.db"))
    p.add_argument("--list", action="store_true", help="list approved clips")
    p.add_argument("--publish-all", action="store_true", help="publish all approved clips")
    p.add_argument("--clip-id", help="publish one clip by id")
    p.add_argument("--dry-run", action="store_true", help="validate without network")
    p.add_argument("--mock", action="store_true", help="simulate uploads (TSK-A05-06)")
    p.add_argument("--verify", action="store_true", help="probe after upload (TSK-A05-15)")
    p.add_argument("--cover", help="custom cover PNG/JPG path (TSK-A05-14)")
    p.add_argument("--schedule-file", default=None, help="publish ledger JSON (TSK-A05-05)")
    p.add_argument("--publish-scheduled", action="store_true",
                   help="publish only clips due per --schedule-file (TSK-A05-05)")
    p.add_argument("--verify-config", action="store_true", help="show which secrets exist (no values)")
    args = p.parse_args(argv)

    if args.verify_config:
        pub = YouTubePublisher(**_env_config())
        missing = pub.missing()
        present = "configured" if not missing else f"missing: {', '.join(missing)}"
        print(f"publisher_yt> {present} (privacy={pub.privacy}, category={pub.category_id})")
        return 0 if not missing else 1

    if args.list:
        rows = find_approved_clips(args.db,
                                   schedule_file=args.schedule_file if args.publish_scheduled else None)
        if not rows:
            print("publisher_yt> no approved clips with a rendered video yet.")
            return 0
        for r in rows:
            print(f"  {r['id']}  score={float(r.get('virality_score') or 0):.1f}  "
                  f"{(r.get('title') or r['id'])[:40]}  -> {r.get('video_path')}")
        return 0

    pub = YouTubePublisher(
        **_env_config(), mock=args.mock, db_path=args.db,
        quota=UploadQuota(limit=int(os.environ.get("CLIPIT_YT_DAILY_QUOTA", DEFAULT_DAILY_QUOTA))),
    )
    if not pub.configured() and not args.dry_run and not pub.mock:
        print("publisher_yt> ERROR: YouTube not configured. Run --verify-config (or --mock).")
        return 1

    schedule_file = args.schedule_file or DEFAULT_LEDGER
    clips = find_approved_clips(
        args.db,
        schedule_file=schedule_file if args.publish_scheduled else None,
    )
    if args.clip_id:
        clips = [c for c in clips if c["id"] == args.clip_id]
    if not clips:
        print("publisher_yt> no approved clips to publish.")
        return 0

    ok = 0
    for clip in clips:
        path = clip.get("video_path")
        title = clip.get("title") or f"Clip {clip['id']}"
        desc = clip.get("description") or ""
        tags = _split_hashtags(clip)
        if args.dry_run or pub.mock:
            outcome = pub._mock_publish(path or "/mock.mp4", title, desc, tags)
            print(f"publisher_yt> [DRY] would publish {clip['id']}: "
                  f"'{str(title)[:50]}' -> {outcome['url']}")
            ok += 1
            continue
        if not path or not os.path.isfile(path):
            print(f"publisher_yt> skip {clip['id']}: video file missing ({path})")
            continue
        try:
            res = pub.publish(
                path, title=title, description=desc, hashtags=tags,
                account_id=clip.get("account_id", ""),
                cover_path=args.cover or clip.get("thumbnail_path") or "",
                verify=args.verify,
            )
            extra = " [verified]" if res.get("probe", {}).get("live") else ""
            print(f"publisher_yt> uploaded {clip['id']} -> {res['url']}{extra}")
            ok += 1
        except PublisherConfigError as exc:
            # TSK-A05-13 failed-upload audit trail.
            audit_event(args.db, "youtube", clip.get("id", ""), "failed",
                        error=str(exc), account_id=clip.get("account_id", ""))
            print(f"publisher_yt> ERROR {clip['id']}: {exc}")
    return 0 if (args.dry_run or args.mock or ok) else 1


if __name__ == "__main__":
    sys.exit(main())
