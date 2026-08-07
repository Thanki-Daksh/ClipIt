"""
tests/test_auto_publisher.py - TSK-A06-09: auto-publisher API tests.

Exercises Agent 05's real publishing modules (modules/publisher_yt,
modules/publisher_ig) against a stub HTTP adapter — no real network, no real
credentials. Asserts the documented API contract:

  * YouTube Shorts: resumable `videos.insert` init (POST → Location header),
    then a body PUT to the resumable session, returning a video_id.
  * Instagram Reels: create media container (POST /media) → poll status
    until FINISHED → POST /media_publish → media_id.

Also asserts the pipeline's metadata package is publish-ready.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import pytest


# ---------------------------------------------------------------------------
# Stub HTTP adapter — mimics the subset of `requests` the publishers use.
# ---------------------------------------------------------------------------

class StubResponse:
    def __init__(self, body: Any, status_code: int = 200,
                 headers: Optional[dict] = None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.text = json.dumps(body)

    def json(self) -> Any:
        return self._body


class StubHTTP:
    """Records calls; returns canned responses routed by (method, url-key)."""

    def __init__(self, routes: Optional[dict] = None):
        """
        routes: {(method, url:  str): StubResponse, ...}
        A call matches when `method` equals and `url-key` appears in the URL.
        Unmatched calls raise AssertionError (so wrong endpoints fail loudly).
        """
        self.routes = routes or {}
        self.calls: list[dict] = []

    def _dispatch(self, method: str, url: str, **kwargs) -> StubResponse:
        self.calls.append({"method": method, "url": url, **kwargs})
        # Longest matching key wins so '/media' can't shadow '/media_publish'.
        best, best_len = None, -1
        for (m, key), resp in self.routes.items():
            if m == method and key in url and len(key) > best_len:
                best, best_len = resp, len(key)
        if best is not None:
            return best
        raise AssertionError(f"no stub route for {method} {url}")

    def post(self, url, **kw) -> StubResponse:
        return self._dispatch("POST", url, **kw)

    def get(self, url, **kw) -> StubResponse:
        return self._dispatch("GET", url, **kw)

    def put(self, url, **kw) -> StubResponse:
        return self._dispatch("PUT", url, **kw)


def _youtube_http() -> StubHTTP:
    """Routes for the 2-step resumable YouTube upload."""
    return StubHTTP(routes={
        ("POST", "googleapis.com/upload/youtube"):
            StubResponse({"snippet": {"title": "s"}},
                         headers={"Location": "https://resumable.example/x"}),
        ("PUT", "resumable.example"):
            StubResponse({"id": "YT123", "status": {"uploadStatus": "uploaded"}}),
    })


def _instagram_http() -> StubHTTP:
    """Routes for media create -> status poll (FINISHED) -> media_publish."""
    return StubHTTP(routes={
        ("POST", "/media"):
            StubResponse({"id": "CREATED_ABC"}),
        ("GET", "CREATED_ABC"):
            StubResponse({"status_code": "FINISHED", "status": "ok"}),
        ("POST", "media_publish"):
            StubResponse({"id": "IG_9988"}),
    })


# ---------------------------------------------------------------------------
# 1) YouTube Shorts publisher (modules.publisher_yt)
# ---------------------------------------------------------------------------

def test_youtube_publisher_uploads_via_resumable_to_video_id(tmp_path):
    from modules.publisher_yt import YouTubePublisher

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video-bytes")
    http = _youtube_http()
    pub = YouTubePublisher(access_token="TOK", http=http)

    result = pub.publish(str(video), title="Viral Hook", description="desc",
                         hashtags=["#shorts"])

    assert result["ok"] is True
    assert result["video_id"] == "YT123"
    assert result["url"] == "https://youtu.be/YT123"

    # Init call carries the OAuth bearer + resumable uploadType.
    init = http.calls[0]
    assert init["method"] == "POST"
    assert init["headers"]["Authorization"] == "Bearer TOK"
    assert init["params"]["uploadType"] == "resumable"
    assert json.loads(init["data"])["snippet"]["title"] == "Viral Hook"

    # Body call PUTs to the resumable Location with the raw file bytes.
    body = http.calls[1]
    assert body["method"] == "PUT"
    assert body["data"] == b"fake-video-bytes"


def test_youtube_publisher_title_capped_and_tags_normalized(tmp_path):
    from modules.publisher_yt import YouTubePublisher

    video = tmp_path / "c.mp4"
    video.write_bytes(b"x")
    http = _youtube_http()
    pub = YouTubePublisher(access_token="TOK", http=http)
    pub.publish(str(video), title="A" * 200, hashtags=["#ones", "two"])

    init_data = json.loads(http.calls[0]["data"])
    assert len(init_data["snippet"]["title"]) == 100
    assert "#ones" in init_data["snippet"]["tags"]


def test_youtube_publisher_raises_when_video_missing(tmp_path):
    from modules.publisher_yt import YouTubePublisher
    with pytest.raises(FileNotFoundError):
        YouTubePublisher(access_token="TOK",
                         http=_youtube_http()).publish(str(tmp_path / "nope.mp4"),
                                                       title="T")


def test_youtube_publisher_requires_upload_location_header(tmp_path):
    """Init response without a Location header must fail before the PUT stage."""
    from modules.publisher_yt import YouTubePublisher
    file = tmp_path / "c.mp4"
    file.write_bytes(b"x")
    bad = StubHTTP(routes={
        ("POST", "upload/youtube"): StubResponse({}),
    })
    with pytest.raises(Exception):
        YouTubePublisher(access_token="TOK", http=bad).publish(str(file), title="T")


# ---------------------------------------------------------------------------
# 2) Instagram Reels publisher (modules.publisher_ig)
# ---------------------------------------------------------------------------

def test_instagram_publisher_two_phase_flow():
    from modules.publisher_ig import InstagramReelsPublisher

    http = _instagram_http()
    pub = InstagramReelsPublisher(access_token="TOK", ig_user_id="user_1",
                                  http=http)
    result = pub.publish(video_url="https://cdn/1.mp4", caption="Hi",
                         hashtags=["#tech"], poll_secs=0)

    assert result["ok"] is True
    assert result["creation_id"] == "CREATED_ABC"
    assert result["media_id"] == "IG_9988"

    # Exactly 3 round-trips: create container, poll status, publish.
    assert len(http.calls) == 3
    create, poll, publish_req = http.calls
    assert create["method"] == "POST" and create["url"].endswith("/media")
    assert create["data"]["media_type"] == "REELS"
    assert "video_url" in create["data"]
    assert poll["url"].endswith("CREATED_ABC")
    assert publish_req["url"].endswith("/media_publish")


def test_instagram_publisher_requires_public_video_url():
    from modules.publisher_ig import (
        InstagramReelsPublisher, PublisherConfigError,
    )
    pub = InstagramReelsPublisher(access_token="TOK", ig_user_id="u",
                                  http=_instagram_http())
    with pytest.raises(PublisherConfigError):
        pub.publish("local_file.mp4", caption="hi")


def test_instagram_publisher_raises_without_auth():
    from modules.publisher_ig import (
        InstagramReelsPublisher, PublisherConfigError,
    )
    with pytest.raises(PublisherConfigError):
        InstagramReelsPublisher(http=_instagram_http()).publish(
            "https://cdn/x.mp4", caption="x")


# ---------------------------------------------------------------------------
# 3) Publish-ready metadata handoff
# ---------------------------------------------------------------------------

def test_metadata_handoff_is_publish_ready(tmp_path):
    from modules.metadata import MetadataCompiler
    compiler = MetadataCompiler(storage_root=str(tmp_path))
    meta = compiler.compile(
        account_id="acc_x", clip_id="clip_acc01_001", video_file="/o/clip.mp4",
        title="Viral Hook", description="Watch this tech clip!",
        hashtags=["tech", "shorts"],
    )
    assert meta["title"] and meta["description"]
    assert all(t.startswith("#") for t in meta["hashtags"])
    pkg = tmp_path / "acc_x" / "outputs" / "metadata.json"
    assert pkg.exists()


def test_metadata_hashtags_normalized(tmp_path):
    from modules.metadata import MetadataCompiler
    compiler = MetadataCompiler(storage_root=str(tmp_path))
    meta = compiler.compile(clip_id="c1", video_file="/o/1.mp4",
                            account_id="acc_y", hashtags=["#Tech", "ai  "])
    assert all(t.startswith("#") and " " not in t for t in meta["hashtags"])
    assert any(t.lower() == "#tech" for t in meta["hashtags"])


def test_instagram_caption_capped_at_2200_chars():
    from modules.publisher_ig import InstagramReelsPublisher
    http = _instagram_http()
    pub = InstagramReelsPublisher(access_token="TOK", ig_user_id="user_1",
                                  http=http)
    pub.publish(video_url="https://cdn/1.mp4", caption="x" * 5000,
                poll_secs=0)
    sent = http.calls[0]["data"]["caption"]
    assert len(sent) <= 2200