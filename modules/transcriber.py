"""
modules/transcriber.py - Groq/OpenAI Whisper Speech-to-Text Transcriber for ClipIt.

Fetches word-level timestamped transcripts using Groq Whisper API (whisper-large-v3)
or OpenAI Whisper API. Handles automatic audio chunking for files > 25MB and exponential retry backoff.
"""

import json
import math
import os
import random
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, TypeVar
import requests
from pydantic import BaseModel, Field

T = TypeVar("T")


def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 4,
    initial_delay: float = 2.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retry_status_codes: Optional[List[int]] = None
) -> T:
    """Execute a callable with exponential retry backoff for rate-limits (429) and server errors (5xx)."""
    status_codes = retry_status_codes or [429, 500, 502, 503, 504]
    delay = initial_delay

    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except requests.exceptions.HTTPError as http_err:
            status = http_err.response.status_code if http_err.response is not None else 0
            if status in status_codes and attempt < max_retries:
                sleep_time = delay + (random.uniform(0, 1.0) if jitter else 0.0)
                print(f"[RetryClient] HTTP {status} encountered. Retrying in {sleep_time:.2f}s (Attempt {attempt}/{max_retries})...")
                time.sleep(sleep_time)
                delay *= backoff_factor
            else:
                raise
        except (requests.exceptions.RequestException, ConnectionError, TimeoutError) as req_err:
            if attempt < max_retries:
                sleep_time = delay + (random.uniform(0, 1.0) if jitter else 0.0)
                print(f"[RetryClient] Network error: {req_err}. Retrying in {sleep_time:.2f}s (Attempt {attempt}/{max_retries})...")
                time.sleep(sleep_time)
                delay *= backoff_factor
            else:
                raise

    raise RuntimeError("Failed after maximum retries.")


class WordTimestamp(BaseModel):
    word: str
    start: float
    end: float


class TranscriptSegment(BaseModel):
    id: int
    start: float
    end: float
    text: str
    words: List[WordTimestamp] = Field(default_factory=list)


class TranscriptResult(BaseModel):
    text: str
    language: str = "en"
    duration: float = 0.0
    segments: List[TranscriptSegment] = Field(default_factory=list)
    words: List[WordTimestamp] = Field(default_factory=list)


class WhisperTranscriber:
    """Speech-to-Text Transcriber supporting Groq Whisper and OpenAI Whisper APIs."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
    OPENAI_API_URL = "https://api.openai.com/v1/audio/transcriptions"
    MAX_FILE_SIZE_BYTES = 24 * 1024 * 1024  # 24MB safety limit (under 25MB Groq/OpenAI cap)

    def __init__(self, api_key: Optional[str] = None, provider: str = "groq", config_path: str = "config.json"):
        self.provider = provider.lower()
        self.api_key = api_key or self._load_api_key_from_env_or_config(config_path)
        if not self.api_key:
            print(f"[Transcriber] WARNING: No API key found for provider '{self.provider}'. Set GROQ_API_KEY / OPENAI_API_KEY environment variable or populate config.json.")

    def _load_api_key_from_env_or_config(self, config_path: str) -> Optional[str]:
        """Load API key from environment or config.json."""
        if self.provider == "groq":
            env_key = os.getenv("GROQ_API_KEY")
            if env_key:
                return env_key
        else:
            env_key = os.getenv("OPENAI_API_KEY")
            if env_key:
                return env_key

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    if self.provider == "groq":
                        return cfg.get("groq_api_key")
                    else:
                        return cfg.get("openai_api_key")
            except Exception as e:
                print(f"[Transcriber] Failed to read config file {config_path}: {e}")
        return None

    def transcribe(self, audio_path: str, model_override: Optional[str] = None) -> TranscriptResult:
        """Transcribe an audio file and return word-level timestamps. Auto-splits > 25MB files."""
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio file not found: {audio_path}")

        file_size = os.path.getsize(audio_path)
        if file_size > self.MAX_FILE_SIZE_BYTES:
            print(f"[Transcriber] Audio file size ({file_size / (1024*1024):.2f}MB) exceeds 25MB limit. Splitting into chunks...")
            return self._transcribe_large_audio(audio_path, model_override)
        else:
            return self._transcribe_chunk(audio_path, time_offset=0.0, model_override=model_override)

    def _transcribe_chunk(self, audio_path: str, time_offset: float = 0.0, model_override: Optional[str] = None) -> TranscriptResult:
        """Send a single audio chunk to the Whisper API with retry backoff."""
        if not self.api_key:
            raise ValueError(f"Missing API key for {self.provider.upper()} STT API.")

        url = self.GROQ_API_URL if self.provider == "groq" else self.OPENAI_API_URL
        default_model = "whisper-large-v3" if self.provider == "groq" else "whisper-1"
        model_name = model_override or default_model

        headers = {
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": model_name,
            "response_format": "verbose_json",
            "timestamp_granularities[]": ["word", "segment"]
        }

        print(f"[Transcriber] Transcribing {os.path.basename(audio_path)} via {self.provider.upper()} ({model_name})...")

        def _make_api_request() -> Dict[str, Any]:
            with open(audio_path, "rb") as audio_file:
                files = {
                    "file": (os.path.basename(audio_path), audio_file, "audio/wav")
                }
                response = requests.post(url, headers=headers, data=data, files=files, timeout=120)
            response.raise_for_status()
            return response.json()

        raw_json = retry_with_backoff(_make_api_request, max_retries=4, initial_delay=3.0)
        return self._parse_whisper_json(raw_json, time_offset=time_offset)

    def _parse_whisper_json(self, raw_json: Dict[str, Any], time_offset: float = 0.0) -> TranscriptResult:
        """Parse Whisper verbose_json output into TranscriptResult with offset adjustment."""
        full_text = raw_json.get("text", "").strip()
        language = raw_json.get("language", "en")
        duration = float(raw_json.get("duration", 0.0))

        raw_segments = raw_json.get("segments", [])
        raw_words = raw_json.get("words", [])

        all_words: List[WordTimestamp] = []
        parsed_segments: List[TranscriptSegment] = []

        # Parse standalone word timestamps if available
        for w in raw_words:
            all_words.append(WordTimestamp(
                word=w.get("word", "").strip(),
                start=round(float(w.get("start", 0.0)) + time_offset, 3),
                end=round(float(w.get("end", 0.0)) + time_offset, 3)
            ))

        # Parse segments
        for idx, seg in enumerate(raw_segments):
            seg_start = round(float(seg.get("start", 0.0)) + time_offset, 3)
            seg_end = round(float(seg.get("end", 0.0)) + time_offset, 3)
            seg_text = seg.get("text", "").strip()

            seg_words: List[WordTimestamp] = []
            for w in seg.get("words", []):
                seg_words.append(WordTimestamp(
                    word=w.get("word", "").strip(),
                    start=round(float(w.get("start", 0.0)) + time_offset, 3),
                    end=round(float(w.get("end", 0.0)) + time_offset, 3)
                ))

            parsed_segments.append(TranscriptSegment(
                id=idx,
                start=seg_start,
                end=seg_end,
                text=seg_text,
                words=seg_words
            ))

        # If top-level words were not present in response, extract words from segments
        if not all_words and parsed_segments:
            for seg in parsed_segments:
                all_words.extend(seg.words)

        return TranscriptResult(
            text=full_text,
            language=language,
            duration=round(duration + time_offset, 3),
            segments=parsed_segments,
            words=all_words
        )

    def _transcribe_large_audio(self, audio_path: str, model_override: Optional[str] = None) -> TranscriptResult:
        """Split large audio file into ~10 minute chunks using FFmpeg and transcribe sequentially."""
        chunk_duration_sec = 600  # 10 minutes per chunk
        total_duration = self._get_audio_duration(audio_path)
        num_chunks = math.ceil(total_duration / chunk_duration_sec) if total_duration > 0 else 1

        combined_text = []
        combined_segments: List[TranscriptSegment] = []
        combined_words: List[WordTimestamp] = []
        detected_language = "en"

        temp_dir = os.path.join(os.path.dirname(audio_path), "chunks_temp")
        os.makedirs(temp_dir, exist_ok=True)

        try:
            for i in range(num_chunks):
                start_sec = i * chunk_duration_sec
                chunk_file = os.path.join(temp_dir, f"chunk_{i:03d}.wav")

                # Extract chunk via FFmpeg
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(start_sec),
                    "-t", str(chunk_duration_sec),
                    "-i", audio_path,
                    "-acodec", "copy",
                    chunk_file
                ]
                subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

                chunk_result = self._transcribe_chunk(chunk_file, time_offset=float(start_sec), model_override=model_override)
                if chunk_result.text:
                    combined_text.append(chunk_result.text)
                detected_language = chunk_result.language

                # Re-index segment IDs
                for seg in chunk_result.segments:
                    seg.id = len(combined_segments)
                    combined_segments.append(seg)

                combined_words.extend(chunk_result.words)

                # Clean up chunk file
                if os.path.exists(chunk_file):
                    os.remove(chunk_file)

        finally:
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir, ignore_errors=True)

        return TranscriptResult(
            text=" ".join(combined_text),
            language=detected_language,
            duration=round(total_duration, 3),
            segments=combined_segments,
            words=combined_words
        )

    def _get_audio_duration(self, audio_path: str) -> float:
        """Probe audio file duration using FFprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ]
        try:
            out = subprocess.check_output(cmd).decode("utf-8").strip()
            return float(out)
        except Exception:
            return 0.0
