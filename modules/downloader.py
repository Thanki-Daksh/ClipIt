"""
modules/downloader.py - yt-dlp Video Downloader & FFmpeg Audio Extractor for ClipIt.

Fetches up to 1080p MP4 video via yt-dlp and extracts 16kHz mono PCM WAV audio
for speech-to-text transcription.
"""

import os
import subprocess
import sys
from typing import Any, Dict, Optional
import yt_dlp
from pydantic import BaseModel, Field


class DownloadResult(BaseModel):
    video_id: str
    title: str
    duration: float
    video_path: str
    audio_path: str
    thumbnail_url: Optional[str] = None
    description: Optional[str] = None
    uploader: Optional[str] = None


class MediaDownloader:
    """yt-dlp Video Downloader and FFmpeg 16kHz Mono Audio Extractor."""

    def __init__(self, output_dir: str = "storage/downloads"):
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_audio_wav(self, input_video_path: str, output_audio_path: str) -> bool:
        """Extract 16kHz mono PCM WAV audio from a video file using FFmpeg."""
        cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file without asking
            "-i", input_video_path,
            "-vn",  # Disable video output
            "-acodec", "pcm_s16le",  # PCM 16-bit little-endian audio codec
            "-ar", "16000",  # 16kHz sample rate (optimal for Whisper STT)
            "-ac", "1",  # Mono channel
            output_audio_path
        ]
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0
        except subprocess.CalledProcessError as e:
            print(f"[Downloader] FFmpeg audio extraction error: {e.stderr.decode('utf-8', errors='replace')}")
            return False
        except Exception as e:
            print(f"[Downloader] FFmpeg error: {e}")
            return False

    def download(self, video_url_or_path: str, video_id_override: Optional[str] = None) -> DownloadResult:
        """Download video and extract 16kHz mono WAV audio."""
        # Handle local video file case
        if os.path.exists(video_url_or_path) or video_url_or_path.startswith("file://"):
            local_path = video_url_or_path.replace("file:///", "").replace("file://", "")
            return self._process_local_file(local_path, video_id_override)

        # Download from YouTube / Web URL via yt-dlp
        vid_id = video_id_override or "video"
        video_filename_template = os.path.join(self.output_dir, f"{vid_id}_%(id)s.%(ext)s")

        ydl_opts = {
            # Format selection: best video <= 1080p + best audio, combined into mp4
            "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
            "outtmpl": video_filename_template,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url_or_path, download=True)
            if not info:
                raise ValueError(f"Failed to extract info for URL: {video_url_or_path}")

            actual_id = info.get("id", vid_id)
            title = info.get("title", "Untitled Video")
            duration = float(info.get("duration", 0))
            thumbnail = info.get("thumbnail")
            description = info.get("description")
            uploader = info.get("uploader")

            # Determine downloaded video path
            downloaded_video_path = ydl.prepare_filename(info)
            # Handle format merge extension change if needed
            base, _ = os.path.splitext(downloaded_video_path)
            if os.path.exists(f"{base}.mp4"):
                downloaded_video_path = f"{base}.mp4"

            if not os.path.exists(downloaded_video_path):
                # Search directory for file starting with target id
                possible_files = [f for f in os.listdir(self.output_dir) if actual_id in f]
                if possible_files:
                    downloaded_video_path = os.path.join(self.output_dir, possible_files[0])

            audio_filename = f"{actual_id}_audio.wav"
            audio_path = os.path.join(self.output_dir, audio_filename)

            # Extract 16kHz mono WAV audio
            print(f"[Downloader] Extracting 16kHz mono audio to {audio_path}...")
            audio_success = self.extract_audio_wav(downloaded_video_path, audio_path)
            if not audio_success:
                raise RuntimeError(f"Audio extraction failed for {downloaded_video_path}")

            return DownloadResult(
                video_id=actual_id,
                title=title,
                duration=duration,
                video_path=downloaded_video_path,
                audio_path=audio_path,
                thumbnail_url=thumbnail,
                description=description,
                uploader=uploader
            )

    def _process_local_file(self, local_path: str, video_id_override: Optional[str] = None) -> DownloadResult:
        """Process a local video file, probe duration, and extract WAV audio."""
        if not os.path.exists(local_path):
            raise FileNotFoundError(f"Local video file not found: {local_path}")

        vid_id = video_id_override or f"local_{abs(hash(local_path))}"
        file_basename = os.path.basename(local_path)
        title = os.path.splitext(file_basename)[0]

        # Probe duration via FFprobe
        duration = self._probe_duration(local_path)

        audio_filename = f"{vid_id}_audio.wav"
        audio_path = os.path.join(self.output_dir, audio_filename)

        print(f"[Downloader] Extracting audio from local file to {audio_path}...")
        audio_success = self.extract_audio_wav(local_path, audio_path)
        if not audio_success:
            raise RuntimeError(f"Failed to extract audio from local file: {local_path}")

        return DownloadResult(
            video_id=vid_id,
            title=title,
            duration=duration,
            video_path=local_path,
            audio_path=audio_path,
            thumbnail_url=None,
            description="Local input video",
            uploader="Local File"
        )

    def _probe_duration(self, file_path: str) -> float:
        """Probe media file duration in seconds using FFprobe."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        try:
            out = subprocess.check_output(cmd).decode("utf-8").strip()
            return float(out)
        except Exception:
            return 0.0
