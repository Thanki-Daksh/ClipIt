"""
tests/test_publishers.py — Agent 05 publisher modules (YT Shorts + IG Reels)
============================================================================
Tests modules/publisher_yt.py and modules/publisher_ig.py without any
network access: a stub HTTP transport simulates the API contracts
(YouTube resumable upload session, Instagram two-phase container flow).
Also covers config verification, approved-clip discovery (both DB schemas),
and the dry-run CLI path.

Run:  python -m pytest tests/test_publishers.py -v
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from modules.publisher_yt import YouTubePublisher, PublisherConfigError as YTErr
from modules.publisher_ig import InstagramReelsPublisher, PublisherConfigError as IGErr
from modules.publisher_yt import find_approved_clips as yt_find
from modules.publisher_ig import find_approved_clips as ig_find


# ---------------------------------------------------------------------------
# Stub HTTP transport — records calls, returns canned API responses
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
    """Records requests; scripts responses per URL substring (longest wins)."""

    def __init__(self):
        self.calls = []  # (method, url, kwargs)
        self.responses = {}  # substring -> FakeResponse
        self.default = FakeResponse(200, {})

    @staticmethod
    def _with_params(url, kwargs):
        """Merge requests-style `params` into the URL like the real lib does."""
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
        self.calls.append((method, url, kwargs))
        return self._respond(url)

    def post(self, url, **kwargs):
        return self._record("POST", url, kwargs)

    def put(self, url, **kwargs):
        return self._record("PUT", url, kwargs)

    def get(self, url, **kwargs):
        return self._record("GET", url, kwargs)


@pytest.fixture
def video_file(tmp_path: Path) -> str:
    p = tmp_path / "clip_abc.mp4"
    p.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
    return str(p)


# ---------------------------------------------------------------------------
# YouTube Shorts publisher
# ---------------------------------------------------------------------------
class TestYouTubePublisher:
    def test_configured_detects_access_token(self):
        pub = YouTubePublisher(access_token="ya29.abc")
        assert pub.configured() is True
        assert pub.missing() == []

    def test_not_configured_lists_missing(self):
        pub = YouTubePublisher()
        assert pub.configured() is False
        assert pub.missing() == ["YOUTUBE_ACCESS_TOKEN OR (YOUTUBE_REFRESH_TOKEN + YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET)"]

    def test_publish_missing_token_raises(self, video_file):
        pub = YouTubePublisher(http=StubHttp())
        with pytest.raises(YTErr):
            pub.publish(video_file, title="T")

    def test_publish_missing_file_raises(self):
        pub = YouTubePublisher(access_token="t", http=StubHttp())
        with pytest.raises(FileNotFoundError):
            pub.publish("/no/such/file.mp4", title="T")

    def test_publish_resumable_flow(self, video_file):
        http = StubHttp()
        # init session -> returns resumable Location (www.googleapis.com/upload)
        http.responses["www.googleapis.com/upload"] = FakeResponse(
            200, {"id": "SHORT123"},
            headers={"Location": "https://upload.youtube.com/resumable?upload_id=xyz"},
        )
        # body stream -> returns the final video metadata with an id
        http.responses["upload.youtube.com"] = FakeResponse(200, {"id": "SHORT123"})
        pub = YouTubePublisher(access_token="ya29.abc", http=http)
        res = pub.publish(
            video_file, title="Best hook ever", description="caption",
            hashtags=["#shorts", "viral", "#clipit"],
        )
        assert res["ok"] is True
        assert res["video_id"] == "SHORT123"
        assert res["url"] == "https://youtu.be/SHORT123"

        methods = [c[0] for c in http.calls]
        assert methods == ["POST", "PUT"]
        init_url = http.calls[0][1]
        assert "uploadType=resumable" in init_url
        body = http.calls[0][2]["data"]
        assert '"privacyStatus": "public"' in body
        assert "categoryId" in body
        assert http.calls[0][2]["headers"]["Authorization"] == "Bearer ya29.abc"
        # file bytes streamed to the resumable URL
        assert http.calls[1][1] == "https://upload.youtube.com/resumable?upload_id=xyz"
        assert http.calls[1][2]["data"].startswith(b"\x00\x00\x00\x18ftyp")

    def test_publish_init_error_raises(self, video_file):
        http = StubHttp()
        http.responses["upload.youtube.com"] = FakeResponse(403, {"error": "quota"}, text="quota")
        pub = YouTubePublisher(access_token="t", http=http)
        with pytest.raises(YTErr):
            pub.publish(video_file, title="T")

    def test_publish_body_error_raises(self, video_file):
        http = StubHttp()
        http.responses["upload.youtube.com"] = FakeResponse(
            200, {}, headers={"Location": "https://up.example/resumable"}
        )
        http.responses["resumable"] = FakeResponse(503, {"error": "busy"}, text="busy")
        pub = YouTubePublisher(access_token="t", http=http)
        with pytest.raises(YTErr):
            pub.publish(video_file, title="T")

    def test_normalize_tags(self):
        pub = YouTubePublisher(access_token="t")
        assert pub._normalize_tags(["#Shorts", "viral clip", "#hook"]) == ["#Shorts", "#viral_clip", "#hook"]
        assert pub._normalize_tags(None) == []


# ---------------------------------------------------------------------------
# Instagram Reels publisher
# ---------------------------------------------------------------------------
class TestInstagramReelsPublisher:
    def test_configured(self):
        pub = InstagramReelsPublisher(access_token="EAAx", ig_user_id="1789")
        assert pub.configured() is True
        assert pub.missing() == []

    def test_missing_secrets(self):
        pub = InstagramReelsPublisher()
        assert pub.configured() is False
        assert pub.missing() == ["INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"]

    def test_local_path_without_public_base_raises(self, video_file):
        pub = InstagramReelsPublisher(access_token="t", ig_user_id="1", http=StubHttp())
        with pytest.raises(IGErr):
            pub.publish(video_file, caption="c")

    def test_resolve_video_url(self):
        pub = InstagramReelsPublisher(access_token="t", ig_user_id="1")
        assert pub._resolve_video_url("https://cdn.example.com/a.mp4") == "https://cdn.example.com/a.mp4"
        pub2 = InstagramReelsPublisher(access_token="t", ig_user_id="1", public_base_url="https://cdn.example.com/clips/")
        assert pub2._resolve_video_url("/tmp/clip_1.mp4") == "https://cdn.example.com/clips/clip_1.mp4"

    def test_publish_two_phase_flow(self, video_file):
        http = StubHttp()
        # container creation -> id 1789_1
        http.responses["/1789/media"] = FakeResponse(200, {"id": "1789_1"})
        # status poll -> FINISHED on first call
        http.responses["1789_1"] = FakeResponse(200, {"status_code": "FINISHED"})
        # publish -> media id
        http.responses["media_publish"] = FakeResponse(200, {"id": "1792_88"})
        pub = InstagramReelsPublisher(
            access_token="EAAx", ig_user_id="1789",
            public_base_url="https://cdn.example.com/clips/", http=http,
        )
        res = pub.publish(video_file, caption="caption", hashtags=["#reels", "viral"])
        assert res["ok"] is True
        assert res["media_id"] == "1792_88"
        assert res["url"] == "https://www.instagram.com/reel/1792_88"

        methods = [c[0] for c in http.calls]
        assert methods == ["POST", "GET", "POST"]
        # container request carries REELS + video_url + caption
        create_body = http.calls[0][2]["data"]
        assert create_body["media_type"] == "REELS"
        assert create_body["video_url"] == "https://cdn.example.com/clips/clip_abc.mp4"
        assert "#reels" in create_body["caption"]
        # poll hits the creation id with fields=status_code
        poll_url = http.calls[1][1]
        assert "1789_1" in poll_url and "status_code" in poll_url
        # publish carries creation_id
        assert http.calls[2][2]["data"]["creation_id"] == "1789_1"

    def test_publish_container_error_raises(self, video_file):
        http = StubHttp()
        http.responses["/1789/media"] = FakeResponse(200, {"id": "1789_1"})
        http.responses["1789_1"] = FakeResponse(200, {"status_code": "ERROR", "status": "bad video"})
        pub = InstagramReelsPublisher(
            access_token="t", ig_user_id="1789",
            public_base_url="https://cdn.example.com/", http=http,
        )
        with pytest.raises(IGErr):
            pub.publish(video_file, caption="c")

    def test_publish_creation_failure_raises(self, video_file):
        http = StubHttp()
        http.responses["/1789/media"] = FakeResponse(400, {"error": {"message": "invalid token"}})
        pub = InstagramReelsPublisher(
            access_token="t", ig_user_id="1789",
            public_base_url="https://cdn.example.com/", http=http,
        )
        with pytest.raises(IGErr):
            pub.publish(video_file, caption="c")


# ---------------------------------------------------------------------------
# Approved-clip discovery (both DB schemas)
# ---------------------------------------------------------------------------
@pytest.fixture
def core_schema_db(tmp_path: Path) -> str:
    """Pipeline schema (core.db): clips has approved INTEGER."""
    db = tmp_path / "core.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE clips (id TEXT PRIMARY KEY, job_id TEXT, account_id TEXT, "
        "start_time REAL, end_time REAL, duration_seconds REAL, virality_score REAL, "
        "hook_text TEXT, video_path TEXT, caption_path TEXT, title TEXT, "
        "description TEXT, hashtags TEXT, approved INTEGER DEFAULT 0, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO clips (id, job_id, account_id, virality_score, video_path, title, approved) "
        "VALUES (?,?,?,?,?,?,?)",
        [
            ("c1", "j1", "a1", 0.9, "/tmp/one.mp4", "One", 1),
            ("c2", "j1", "a1", 0.8, "/tmp/two.mp4", "Two", 0),
            ("c3", "j2", "a2", 0.7, "", "Three", 1),
        ],
    )
    conn.commit()
    conn.close()
    return str(db)


@pytest.fixture
def ui_schema_db(tmp_path: Path) -> str:
    """Legacy UI/seed schema: clips has status TEXT."""
    db = tmp_path / "ui.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE clips (id TEXT PRIMARY KEY, video_url TEXT, source_title TEXT, "
        "account_id TEXT, start_time REAL, end_time REAL, duration REAL, "
        "virality_score REAL, hook_summary TEXT, status TEXT DEFAULT 'pending', "
        "video_path TEXT, thumbnail_path TEXT, subtitles_json TEXT, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.executemany(
        "INSERT INTO clips (id, account_id, virality_score, status, video_path) "
        "VALUES (?,?,?,?,?)",
        [
            ("u1", "a1", 0.9, "approved", "/tmp/up1.mp4"),
            ("u2", "a1", 0.8, "pending", "/tmp/up2.mp4"),
        ],
    )
    conn.commit()
    conn.close()
    return str(db)


class TestDiscovery:
    def test_core_schema_only_approved_with_video(self, core_schema_db):
        rows = yt_find(core_schema_db)
        assert [r["id"] for r in rows] == ["c1"]  # c2 unapproved, c3 no video

    def test_ui_schema_approved_status(self, ui_schema_db):
        rows = ig_find(ui_schema_db)
        assert [r["id"] for r in rows] == ["u1"]

    def test_missing_db_returns_empty(self):
        assert yt_find("/no/such/db.sqlite") == []
        assert ig_find("/no/such/db.sqlite") == []


# ---------------------------------------------------------------------------
# CLI dry-run path (no secrets needed)
# ---------------------------------------------------------------------------
class TestCliDryRun:
    def test_yt_dry_run_exits_zero(self, ui_schema_db, capsys):
        from modules.publisher_yt import main as yt_main
        code = yt_main(["--db", ui_schema_db, "--publish-all", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "[DRY] would publish u1" in out

    def test_ig_dry_run_exits_zero(self, ui_schema_db, capsys):
        from modules.publisher_ig import main as ig_main
        code = ig_main(["--db", ui_schema_db, "--publish-all", "--dry-run"])
        out = capsys.readouterr().out
        assert code == 0
        assert "[DRY] would publish u1" in out

    def test_verify_config_reports_missing(self, capsys, monkeypatch):
        monkeypatch.delenv("YOUTUBE_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
        monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
        monkeypatch.delenv("YOUTUBE_CLIENT_SECRET", raising=False)
        from modules.publisher_yt import main as yt_main
        code = yt_main(["--verify-config"])
        assert code == 1
        assert "missing" in capsys.readouterr().out

    def test_verify_config_ok_when_secret_set(self, capsys, monkeypatch):
        monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "ya29.test")
        from modules.publisher_yt import main as yt_main
        assert yt_main(["--verify-config"]) == 0
        assert "configured" in capsys.readouterr().out

    def test_ig_verify_config_missing(self, capsys, monkeypatch):
        monkeypatch.delenv("INSTAGRAM_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("INSTAGRAM_USER_ID", raising=False)
        from modules.publisher_ig import main as ig_main
        assert ig_main(["--verify-config"]) == 1
        assert "INSTAGRAM_ACCESS_TOKEN" in capsys.readouterr().out
