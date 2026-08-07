"""
modules/watcher.py - YouTube RSS Feed Parser & Watch Folder Observer for ClipIt.

Parses YouTube channel RSS feeds (by Channel ID, @handle, or URL) and scans local
watch directories for new video files.
"""

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field


class VideoItem(BaseModel):
    video_id: str
    title: str
    url: str
    published_at: Optional[str] = None
    channel_id: Optional[str] = None
    channel_title: Optional[str] = None
    thumbnail_url: Optional[str] = None
    source_type: str = "youtube"  # 'youtube' or 'local'
    file_path: Optional[str] = None


class YouTubeWatcher:
    """YouTube RSS Feed parser and watch directory observer."""

    RSS_BASE_URL = "https://www.youtube.com/feeds/videos.xml"
    ATOM_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.session = requests.Session()
        self.session.headers.update(headers or {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def extract_channel_id(self, channel_input: str) -> Optional[str]:
        """Extract YouTube channel ID from direct ID, @handle, or channel URL."""
        channel_input = channel_input.strip()

        # Direct channel ID format (starts with UC...)
        if re.match(r"^UC[\w-]{22}$", channel_input):
            return channel_input

        # URL containing channel ID
        match = re.search(r"youtube\.com/channel/(UC[\w-]{22})", channel_input)
        if match:
            return match.group(1)

        # Handle or vanity URL resolution via HTML fetch
        url = channel_input
        if not url.startswith("http"):
            if channel_input.startswith("@"):
                url = f"https://www.youtube.com/{channel_input}"
            else:
                url = f"https://www.youtube.com/c/{channel_input}"

        try:
            resp = self.session.get(url, timeout=10)
            if resp.status_code == 200:
                # Look for browse_id or rssUrl in page source
                match_id = re.search(r'"browseId":"(UC[\w-]{22})"', resp.text)
                if match_id:
                    return match_id.group(1)
                match_rss = re.search(r'rssUrl="https://www\.youtube\.com/feeds/videos\.xml\?channel_id=(UC[\w-]{22})"', resp.text)
                if match_rss:
                    return match_rss.group(1)
        except Exception as e:
            print(f"[Watcher] Error resolving channel ID for {channel_input}: {e}")

        return None

    def fetch_rss_feed(self, channel_input: str) -> List[VideoItem]:
        """Fetch and parse RSS feed for a YouTube channel."""
        channel_id = self.extract_channel_id(channel_input)
        if not channel_id:
            print(f"[Watcher] Unable to determine channel ID for: {channel_input}")
            return []

        rss_url = f"{self.RSS_BASE_URL}?channel_id={channel_id}"
        try:
            resp = self.session.get(rss_url, timeout=10)
            if resp.status_code != 200:
                print(f"[Watcher] RSS HTTP {resp.status_code} for channel {channel_id}")
                return []
            return self._parse_rss_xml(resp.text)
        except Exception as e:
            print(f"[Watcher] Error fetching RSS feed for channel {channel_id}: {e}")
            return []

    def _parse_rss_xml(self, xml_text: str) -> List[VideoItem]:
        """Parse YouTube Atom XML feed into VideoItem models."""
        items: List[VideoItem] = []
        try:
            root = ET.fromstring(xml_text)
            entries = root.findall("atom:entry", self.ATOM_NS)
            for entry in entries:
                video_id_elem = entry.find("yt:videoId", self.ATOM_NS)
                title_elem = entry.find("atom:title", self.ATOM_NS)
                link_elem = entry.find("atom:link", self.ATOM_NS)
                published_elem = entry.find("atom:published", self.ATOM_NS)
                author_elem = entry.find("atom:author/atom:name", self.ATOM_NS)
                channel_id_elem = entry.find("yt:channelId", self.ATOM_NS)

                if video_id_elem is not None and video_id_elem.text:
                    vid = video_id_elem.text
                    title = title_elem.text if title_elem is not None else "Untitled"
                    link = link_elem.attrib.get("href") if link_elem is not None else f"https://www.youtube.com/watch?v={vid}"
                    published = published_elem.text if published_elem is not None else None
                    author = author_elem.text if author_elem is not None else None
                    chan_id = channel_id_elem.text if channel_id_elem is not None else None

                    thumb_url = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"

                    items.append(VideoItem(
                        video_id=vid,
                        title=title,
                        url=link,
                        published_at=published,
                        channel_id=chan_id,
                        channel_title=author,
                        thumbnail_url=thumb_url,
                        source_type="youtube"
                    ))
        except ET.ParseError as pe:
            print(f"[Watcher] XML parse error: {pe}")
        return items

    def poll_channels(self, channel_inputs: List[str]) -> List[VideoItem]:
        """Poll multiple channels and return aggregated video list."""
        all_videos: List[VideoItem] = []
        for channel_input in channel_inputs:
            videos = self.fetch_rss_feed(channel_input)
            all_videos.extend(videos)
        return all_videos

    @staticmethod
    def scan_watch_folder(folder_path: str, valid_extensions: Optional[List[str]] = None) -> List[VideoItem]:
        """Scan local watch folder for un-processed video files."""
        if not os.path.exists(folder_path):
            return []

        extensions = valid_extensions or [".mp4", ".mkv", ".webm", ".mov", ".avi"]
        items: List[VideoItem] = []

        for root_dir, _, files in os.walk(folder_path):
            for file_name in files:
                ext = os.path.splitext(file_name)[1].lower()
                if ext in extensions:
                    full_path = os.path.join(root_dir, file_name)
                    video_id = f"local_{abs(hash(full_path))}"
                    file_stat = os.stat(full_path)
                    mod_time = datetime.fromtimestamp(file_stat.st_mtime).isoformat()

                    items.append(VideoItem(
                        video_id=video_id,
                        title=os.path.splitext(file_name)[0],
                        url=f"file:///{full_path.replace('\\', '/')}",
                        published_at=mod_time,
                        source_type="local",
                        file_path=full_path
                    ))
        return items
