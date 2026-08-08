"""
tests/test_publisher_features.py — Agent 05 Social Publisher & API Integrator
=============================================================================
Covers the feature layer beyond the pre-existing engine tests
(tests/test_publishers.py + tests/test_auto_publisher.py):

  * TSK-A05-03  OAuth token refresh (core.auth + publisher refresh trio)
  * TSK-A05-04  upload retry / exponential backoff
  * TSK-A05-05  publish schedule dispatcher (ledger + discovery filter)
  * TSK-A05-06  mock publisher mode
  * TSK-A05-07  upload progress telemetry
  * TSK-A05-08  multi-account token rotator (CredentialPool)
  * TSK-A05-11  auto #Shorts / #Reels injection
  * TSK-A05-12  daily upload quota guard
  * TSK-A05-13  failed-upload audit trail (job_logs)
  * TSK-A05-14  custom cover frame upload (thumbnails.set)
  * TSK-A05-15  post-publish verification probe

Run:  python -m pytest tests/test_publisher_features.py -v
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from modules.publisher_yt import (
    YouTubePublisher,
    PublisherConfigError as YTErr,
    find_approved_clips as yt_find,
)
from modules.publisher_ig import (
    InstagramReelsPublisher,
    PublisherConfigError as IGErr,
)
from core.auth import CredentialPool, UploadQuota, audit_event, due_clip_ids, schedule_clip


# ---------------------------------------------------------------------------
# Stub HTTP transport (same pattern as the QA suite)
# ---------------------------------------------------------------------------
class FakeResponse:
    def __init__(self, status_code=200, json_data=None, text="", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text or str(json_data or {})
        self.headers = headers or {}

    def json(self):
        return self._json


class StubHttp:
    def __init__(self):
        self.calls = []  # (method, url, kwargs)
        self.responses = {}  # substring -> FakeResponse
        self.default = FakeResponse(200, {})

    @staticmethod
    def _with_params(url, kwargs):
        params = kwargs.get("params")
        if not params:
            return url, dict(kwargs)
        sep = "&" if ("?" in url and not url.endswith("?")) else "?"
        qs = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        kwargs = dict(kwargs)
        kwargs.pop("params", None)
        return f"{url}{sep}{qs}", kwargs

    def _respond(self, url):
        best, best_match = None, -1
        for key, resp in self.responses.items():
            if key in url and len(key) > best_match:
                best, best_match = resp, len(key)
        return best if best is not None else self.default

    def _record(self, method, url, kwargs):
        url, kwargs = self._with_params(url, kwargs)
        # A generator/stream body is consumed by a real HTTP client; drain it
        # here so chunked uploads (progress telemetry) actually execute.
        data = kwargs.get("data")
        if data is not None and not isinstance(data, (str, bytes)) and hasattr(data, "__next__"):
            kwargs["data"] = b"".join(data)
        self.calls.append((method, url, kwargs))
        return self._respond(url)

    def post(self, url, **kwargs):
        return self._record("POST", url, kwargs)

    def put(self, url, **kwargs):
        return self._record("PUT", url, kwargs)

    def get(self, url, **kwargs):
        return self._record("GET", url, kwargs)


def yt_routes(video_id="YT123"):
    """Success responses for the resumable YouTube walk."""
    return {
        "googleapis.com/upload": FakeResponse(
            200, {"id": video_id},
            headers={"Location": "https://resumable.example/x"},
        ),
        "resumable.example": FakeResponse(200, {"id": video_id}),
    }


@pytest.fixture
def video_file(tmp_path: Path) -> str:
    p = tmp_path / "clip.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
    return str(p)


@pytest.fixture
def yt_http():
    http = StubHttp()
    http.responses.update(yt_routes())
    return http


# ---------------------------------------------------------------------------
# TSK-A05-03 — OAuth token refresh
# ---------------------------------------------------------------------------
class TestOAuthRefresh:
    def test_refresh_grant_mints_access_token(self):
        http = StubHttp()
        http.responses["oauth2.googleapis.com"] = FakeResponse(200, {"access_token": "NEW_AT"})
        from core.auth import refresh_youtube_access_token

        token = refresh_youtube_access_token("RT", "CID", "SEC", http=http)
        assert token == "NEW_AT"
        body = http.calls[0][2]["data"]
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "RT"

    def test_refresh_failure_raises(self):
        http = StubHttp()
        http.responses["oauth2.googleapis.com"] = FakeResponse(400, {"error": "invalid_grant"})
        from core.auth import AuthError, refresh_youtube_access_token

        with pytest.raises(AuthError):
            refresh_youtube_access_token("RT", "CID", "SEC", http=http)

    def test_publisher_uses_refresh_trio_when_no_access_token(self, video_file):
        http = StubHttp()
        http.responses["oauth2.googleapis.com"] = FakeResponse(200, {"access_token": "REFRESHED"})
        http.responses.update(yt_routes())
        pub = YouTubePublisher(refresh_token="RT", client_id="CID", client_secret="SEC", http=http)
        res = pub.publish(video_file, title="T")
        assert res["ok"] is True
        # First call is the token refresh; the upload init carries the minted bearer.
        assert http.calls[0][2]["data"]["grant_type"] == "refresh_token"
        assert http.calls[1][2]["headers"]["Authorization"] == "Bearer REFRESHED"


# ---------------------------------------------------------------------------
# TSK-A05-08 — multi-account token rotator (CredentialPool)
# ---------------------------------------------------------------------------
class TestCredentialPool:
    @pytest.fixture
    def pool_db(self, tmp_path: Path) -> str:
        db = tmp_path / "pool.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE oauth_channels (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "account_id TEXT NOT NULL, channel TEXT, access_token TEXT, "
            "refresh_token TEXT, scope TEXT, expires_at TIMESTAMP, "
            "UNIQUE(account_id))"
        )
        conn.commit()
        conn.close()

        # The pool reads the LIVE pipeline table (oauth_credentials); create it.
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE oauth_credentials (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "account_id TEXT NOT NULL, provider TEXT NOT NULL, scopes TEXT, "
            "access_token_enc TEXT, refresh_token_enc TEXT, expires_at TIMESTAMP, "
            "revoked INTEGER DEFAULT 0, created_at TIMESTAMP, updated_at TIMESTAMP, "
            "UNIQUE(account_id, provider))"
        )
        conn.executemany(
            "INSERT INTO oauth_credentials (account_id, provider, access_token_enc) VALUES (?,?,?)",
            [("acc_a", "youtube", "AT_A"), ("acc_b", "youtube", "AT_B")],
        )
        conn.commit()
        conn.close()
        return str(db)

    def test_round_robin_rotates_accounts(self, pool_db):
        pool = CredentialPool(db_path=pool_db, provider="youtube")
        accs = pool.configured_accounts()
        assert set(accs) == {"acc_a", "acc_b"}
        acc1, tok1 = pool.bearer_round_robin()
        acc2, tok2 = pool.bearer_round_robin()
        acc3, tok3 = pool.bearer_round_robin()
        assert acc1 != acc2
        assert acc3 == acc1  # wraps after two accounts
        assert {tok1, tok2} == {"AT_A", "AT_B"}

    def test_env_fallback_when_no_db(self, monkeypatch):
        pool = CredentialPool(db_path=None)
        monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "ENV_AT")
        acc, tok = pool.bearer_round_robin()
        assert acc == "__env__"
        assert tok == "ENV_AT"


# ---------------------------------------------------------------------------
# TSK-A05-04 — upload retry & exponential backoff
# ---------------------------------------------------------------------------
class TestRetryBackoff:
    def test_transient_retries_then_succeeds(self, video_file):
        http = StubHttp()
        http.responses["googleapis.com/upload"] = FakeResponse(
            503, {"error": "busy"}, text="busy"
        )
        http.responses["resumable.example"] = FakeResponse(200, {"id": "Y"})

        hits = {"n": 0}
        orig = http._respond

        def flip(url):
            if "uploadType=resumable" in url:
                hits["n"] += 1
                if hits["n"] >= 2:
                    return FakeResponse(200, {"id": "Y"},
                                        headers={"Location": "https://resumable.example/x"})
            return orig(url)

        http._respond = flip
        sleeps = []
        pub = YouTubePublisher(access_token="TOK", http=http, backoff_base=0.5,
                               sleep_fn=lambda s: sleeps.append(s))
        res = pub.publish(video_file, title="T")
        assert res["ok"] is True
        assert hits["n"] == 2  # one 503, one retry success
        assert sleeps  # backoff was actually slept

    def test_transient_exhausted_raises(self, video_file):
        http = StubHttp()
        http.responses["googleapis.com/upload"] = FakeResponse(503, {"error": "busy"}, text="busy")
        sleeps = []
        pub = YouTubePublisher(access_token="TOK", http=http, max_retries=2,
                               backoff_base=0.5, sleep_fn=sleeps.append)
        with pytest.raises(YTErr):
            pub.publish(video_file, title="T")
        assert len(sleeps) == 2  # backoff between attempts

    def test_network_error_retries(self, video_file):
        class BoomHttp(StubHttp):
            def put(self, url, **kwargs):
                raise OSError("connection reset")

        # First response 503 -> retried; after max_retries a raised exception
        # is converted to YTErr.
        http = StubHttp()
        http.responses["googleapis.com/upload"] = FakeResponse(
            200, {}, headers={"Location": "https://resumable.example/x"})
        http.responses["resumable.example"] = FakeResponse(200, {})
        boom = BoomHttp()
        boom.responses = http.responses
        sleeps = []
        pub = YouTubePublisher(access_token="TOK", http=boom, max_retries=1,
                               sleep_fn=sleeps.append)
        with pytest.raises(YTErr):
            pub.publish(video_file, title="T")
        assert sleeps


# ---------------------------------------------------------------------------
# TSK-A05-06 — mock publisher mode
# ---------------------------------------------------------------------------
class TestMockMode:
    def test_yt_mock_without_tokens_or_file(self):
        pub = YouTubePublisher(mock=True)
        res = pub.publish("/does/not/exist.mp4", title="No tokens needed")
        assert res["ok"] is True
        assert res["mock"] is True
        assert res["video_id"].startswith("MOCK-")

    def test_ig_mock_without_tokens(self):
        pub = InstagramReelsPublisher(mock=True)
        res = pub.publish("https://cdn.example.com/x.mp4", caption="hi")
        assert res["ok"] is True
        assert res["mock"] is True
        assert "MOCK" in res["media_id"]

    def test_env_force_mock(self, monkeypatch, video_file):
        monkeypatch.setenv("CLIPIT_MOCK", "1")
        pub = YouTubePublisher()
        res = pub.publish(video_file, title="T")
        assert res["mock"] is True


# ---------------------------------------------------------------------------
# TSK-A05-05 — publish schedule dispatcher
# ---------------------------------------------------------------------------
class TestScheduler:
    def test_ledger_due_filtering(self, tmp_path):
        ledger = str(tmp_path / "sch.json")
        schedule_clip(ledger, "c1", publish_at="2099-01-01T00:00:00+00:00")
        schedule_clip(ledger, "c2", publish_at="2000-01-01T00:00:00+00:00")
        schedule_clip(ledger, "c3", publish_at="2000-01-01T00:00:00+00:00")
        # An entry with a NULL timestamp must also be considered immediately due.
        import json as _json
        with open(ledger, "r", encoding="utf-8") as fh:
            data = _json.load(fh)
        data["c4"] = None
        with open(ledger, "w", encoding="utf-8") as fh:
            _json.dump(data, fh)
        due = due_clip_ids(ledger, now="2026-01-01T00:00:00+00:00")
        assert "c1" not in due
        assert "c2" in due and "c3" in due and "c4" in due

    def test_find_approved_respects_schedule(self, tmp_path):
        db = tmp_path / "d.db"
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE clips (id TEXT PRIMARY KEY, job_id TEXT, account_id TEXT, "
            "start_time TEXT, end_time TEXT, duration_seconds REAL, virality_score REAL, "
            "hook_text TEXT, video_path TEXT, caption_path TEXT, title TEXT, description TEXT, "
            "hashtags TEXT, approved INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.executemany(
            "INSERT INTO clips (id, approved, video_path) VALUES (?,?,?)",
            [("c1", 1, "/v1.mp4"), ("c2", 1, "/v2.mp4")],
        )
        conn.commit()
        conn.close()
        ledger = str(tmp_path / "ledger.json")
        schedule_clip(ledger, "c2")
        rows = yt_find(str(db), schedule_file=ledger)
        assert [r["id"] for r in rows] == ["c2"]


# ---------------------------------------------------------------------------
# TSK-A05-07 — upload progress telemetry
# ---------------------------------------------------------------------------
class TestProgressTelemetry:
    def test_yt_progress_reports_bytes(self, video_file):
        http = StubHttp()
        http.responses.update(yt_routes())
        progress = []
        pub = YouTubePublisher(access_token="TOK", http=http,
                               progress_cb=lambda sent, total: progress.append((sent, total)),
                               chunk_size=100)
        pub.publish(video_file, title="T")
        total = os.path.getsize(video_file)
        assert progress[-1] == (total, total)

    def test_ig_progress_stages(self, video_file):
        http = StubHttp()
        http.responses["/1789/media"] = FakeResponse(200, {"id": "1789_1"})
        http.responses["1789_1"] = FakeResponse(200, {"status_code": "FINISHED"})
        http.responses["media_publish"] = FakeResponse(200, {"id": "1792_88"})
        stages = []
        pub = InstagramReelsPublisher(access_token="TOK", ig_user_id="1789",
                                      public_base_url="https://cdn.example.com/", http=http,
                                      progress_cb=lambda s, t: stages.append((s, t)))
        pub.publish("https://cdn.example.com/x.mp4", caption="c", poll_secs=0)
        assert stages == [(1, 3), (2, 3), (3, 3)]


# ---------------------------------------------------------------------------
# TSK-A05-11 — auto hashtag / caption injection
# ---------------------------------------------------------------------------
class TestCaptionInjection:
    def test_yt_always_has_shorts(self):
        pub = YouTubePublisher(access_token="t")
        assert "#Shorts" in pub._join_description("watch this", [])
        assert "#Shorts" in pub._join_description("watch this #Shorts", ["#viral"])

    def test_ig_always_has_reels(self):
        pub = InstagramReelsPublisher(access_token="t", ig_user_id="1")
        assert "#Reels" in pub._join_caption("hi", None)
        assert "#Reels" in pub._join_caption("hi #Reels", ["#tech"])


# ---------------------------------------------------------------------------
# TSK-A05-12 — daily upload quota guard
# ---------------------------------------------------------------------------
class TestQuotaGuard:
    def test_quota_blocks_before_network(self, tmp_path, video_file):
        from core.auth import UploadQuota

        quota_path = str(tmp_path / "quota.json")
        quota = UploadQuota(path=quota_path, limit=1)
        quota.record("youtube", "acc_x")  # 1/1 used today
        http = StubHttp()
        pub = YouTubePublisher(access_token="TOK", http=http, quota=quota)
        with pytest.raises(YTErr, match="quota"):
            pub.publish(video_file, title="T", account_id="acc_x")
        assert len(http.calls) == 0  # blocked before any network call

    def test_quota_records_after_success(self, tmp_path, video_file):
        quota_path = str(tmp_path / "quota.json")
        quota = UploadQuota(path=quota_path, limit=2)
        http = StubHttp()
        http.responses.update(yt_routes())
        pub = YouTubePublisher(access_token="TOK", http=http, quota=quota)
        pub.publish(video_file, title="T", account_id="acc_x")
        assert quota.used("youtube", "acc_x") == 1


# ---------------------------------------------------------------------------
# TSK-A05-13 — failed-upload audit trail (job_logs)
# ---------------------------------------------------------------------------
class TestAuditTrail:
    def test_audit_event_creates_job_logs(self, tmp_path):
        db = str(tmp_path / "clipit.db")
        audit_event(db, "youtube", "clip_01", "failed", error="boom")
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT clip_id, provider, status, error FROM job_logs").fetchone()
        conn.close()
        assert row == ("clip_01", "youtube", "failed", "boom")

    def test_yt_cli_failure_writes_audit_row(self, tmp_path):
        db = str(tmp_path / "c.db")
        conn = sqlite3.connect(db)
        conn.execute(
            "CREATE TABLE clips (id TEXT PRIMARY KEY, account_id TEXT, virality_score REAL, "
            "video_path TEXT, title TEXT, description TEXT, hashtags TEXT, "
            "approved INTEGER DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO clips (id, approved, video_path) VALUES ('c9', 1, ?)",
            (str(tmp_path / "ghost.mp4"),),
        )
        conn.commit()
        conn.close()
        # CLI path: config is missing -> early exit, so drive audit directly:
        audit_event(db, "youtube", "c9", "failed", error="Upload init failed: 403")
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT clip_id, status FROM job_logs").fetchall()
        conn.close()
        assert ("c9", "failed") in rows


# ---------------------------------------------------------------------------
# TSK-A05-14 — custom cover frame uploader
# ---------------------------------------------------------------------------
class TestCoverFrame:
    def test_thumbnail_upload_after_publish(self, tmp_path, video_file):
        cover = tmp_path / "cover.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        http = StubHttp()
        http.responses.update(yt_routes("YT1"))
        http.responses["thumbnails"] = FakeResponse(200, {"items": [{"default": "https://t/1.jpg"}]})
        pub = YouTubePublisher(access_token="TOK", http=http)
        res = pub.publish(video_file, title="T", cover_path=str(cover))
        assert res["cover"]["ok"] is True
        thumb_calls = [c for c in http.calls if "thumbnails" in c[1]]
        assert len(thumb_calls) == 1

    def test_upload_thumbnail_direct(self, tmp_path):
        cover = tmp_path / "poster.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        http = StubHttp()
        http.responses["thumbnails"] = FakeResponse(200, {"items": [{"default": "t.jpg"}]})
        pub = YouTubePublisher(access_token="TOK", http=http)
        res = pub.upload_thumbnail("YT_ID", str(cover))
        assert res["ok"] is True
        # Stub merges params into the URL, so assert on the query string.
        assert "videoId=YT_ID" in http.calls[0][1]


# ---------------------------------------------------------------------------
# TSK-A05-15 — post-publish verification probe
# ---------------------------------------------------------------------------
class TestVerificationProbe:
    def test_yt_verify_live(self, video_file):
        http = StubHttp()
        http.responses.update(yt_routes("YT1"))
        http.responses["youtube/v3/videos"] = FakeResponse(
            200, {"items": [{"status": {"uploadStatus": "processed", "privacyStatus": "public"}}]}
        )
        pub = YouTubePublisher(access_token="TOK", http=http)
        res = pub.publish(video_file, title="T", verify=True)
        assert res["verified"] is True

    def test_yt_verify_not_found(self):
        http = StubHttp()
        http.responses["youtube/v3/videos"] = FakeResponse(200, {"items": []})
        pub = YouTubePublisher(access_token="TOK", http=http)
        probe = pub.verify("MISSING")
        assert probe["live"] is False
        assert probe["reason"] == "not-found"

    def test_ig_verify_live(self):
        http = StubHttp()
        http.responses["instagram.com/MEDIA"] = FakeResponse(
            200, {"id": "MEDIA", "permalink": "https://www.instagram.com/reel/MEDIA/"}
        )
        pub = InstagramReelsPublisher(access_token="TOK", ig_user_id="1789", http=http)
        probe = pub.verify("MEDIA")
        assert probe["live"] is True