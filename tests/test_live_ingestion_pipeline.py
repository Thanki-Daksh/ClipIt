"""
tests/test_live_ingestion_pipeline.py - Real Ingestion Pipeline Integration Test for TSK-A02-09 and TSK-A02-10.

Downloads real YouTube video stream via yt-dlp, transcribes audio to get word-level timestamps,
and runs virality analyzer to extract high-hook viral clips.
"""

import os
import unittest
from pathlib import Path

import pytest

from modules.watcher import YouTubeWatcher
from modules.downloader import MediaDownloader
from modules.transcriber import WhisperTranscriber
from modules.analyzer import ViralityAnalyzer

# QA gate (Agent 06): this suite hits the REAL network (yt-dlp -> YouTube) and
# real STT/LLM providers (Whisper/Groq, Gemini). It must stay OUT of the default
# deterministic suite; run explicitly with CLIPIT_LIVE_NETWORK=1 when the keys
# are configured:  CLIPIT_LIVE_NETWORK=1 python -m pytest -v tests/test_live_ingestion_pipeline.py
pytestmark = pytest.mark.skipif(
    os.environ.get("CLIPIT_LIVE_NETWORK") != "1",
    reason="live-network + API-key integration test: set CLIPIT_LIVE_NETWORK=1 to run",
)

class TestLiveIngestionPipeline(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.downloader = MediaDownloader(output_dir="storage/downloads_test")
        cls.transcriber = WhisperTranscriber()
        cls.analyzer = ViralityAnalyzer()

    def test_live_youtube_download_transcribe_and_analyze(self):
        """Test complete real pipeline on a sample short YouTube video."""
        # Use a reliable public short video URL (e.g. YouTube sample video)
        sample_url = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo" - 19 seconds

        # 1. Ingest/Download via yt-dlp (allow shorts for test clip)
        downloader = MediaDownloader(output_dir="storage/downloads_test", filter_shorts=False, filter_live=True)
        print(f"\n[TestPipeline] Step 1: Downloading video from {sample_url}...")
        download_res = downloader.download(sample_url, video_id_override="test_zoo_video")

        self.assertIsNotNone(download_res.video_path)
        self.assertTrue(os.path.exists(download_res.video_path))
        self.assertTrue(os.path.exists(download_res.audio_path))
        self.assertGreater(os.path.getsize(download_res.audio_path), 0)
        print(f"[TestPipeline] Downloaded: '{download_res.title}' ({download_res.duration:.1f}s)")
        print(f"[TestPipeline] Audio path: {download_res.audio_path}")

        # 2. Transcribe via Whisper STT API to fetch word-level timestamps
        print("[TestPipeline] Step 2: Transcribing audio with Whisper STT...")
        transcription = self.transcriber.transcribe(download_res.audio_path)

        self.assertIsNotNone(transcription.text)
        self.assertGreater(len(transcription.text), 0)
        print(f"[TestPipeline] Transcript text ({len(transcription.words)} words): '{transcription.text}'")

        # 3. Analyze Transcript via Virality Analyzer
        print("[TestPipeline] Step 3: Running virality analysis & hook extraction...")
        analysis = self.analyzer.analyze_transcript(
            video_title=download_res.title,
            video_duration=download_res.duration,
            transcript_segments=transcription.segments,
            max_clips=3
        )

        self.assertEqual(analysis.video_title, download_res.title)
        print(f"[TestPipeline] Pipeline finished. Extracted {len(analysis.clips)} candidate clips.")
        for idx, clip in enumerate(analysis.clips, 1):
            print(f"   Clip #{idx}: [{clip.start_time:.1f}s -> {clip.end_time:.1f}s] Score={clip.virality_score} Headline='{clip.headline}' Hook='{clip.hook_text}'")


if __name__ == "__main__":
    unittest.main()
