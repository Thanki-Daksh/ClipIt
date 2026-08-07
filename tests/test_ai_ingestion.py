"""
tests/test_ai_ingestion.py - Unit & Integration Tests for Agent 02 (AI & Ingestion Specialist).
"""

import os
import unittest
from unittest.mock import MagicMock, patch

from modules.watcher import YouTubeWatcher, VideoItem
from modules.downloader import MediaDownloader, DownloadResult
from modules.transcriber import WhisperTranscriber, TranscriptResult, TranscriptSegment, WordTimestamp
from modules.analyzer import ViralityAnalyzer, ViralityAnalysisResult, ViralClipCandidate


class TestYouTubeWatcher(unittest.TestCase):

    def setUp(self):
        self.watcher = YouTubeWatcher()

    def test_extract_channel_id_direct(self):
        channel_id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
        result = self.watcher.extract_channel_id(channel_id)
        self.assertEqual(result, channel_id)

    def test_parse_rss_xml(self):
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
            <title>Test Channel</title>
            <entry>
                <id>yt:video:test_vid_123</id>
                <yt:videoId>test_vid_123</yt:videoId>
                <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
                <title>Test Video Title</title>
                <link rel="alternate" href="https://www.youtube.com/watch?v=test_vid_123"/>
                <published>2026-08-07T12:00:00+00:00</published>
            </entry>
        </feed>
        """
        videos = self.watcher._parse_rss_xml(sample_xml)
        self.assertEqual(len(videos), 1)
        self.assertEqual(videos[0].video_id, "test_vid_123")
        self.assertEqual(videos[0].title, "Test Video Title")
        self.assertEqual(videos[0].source_type, "youtube")


class TestTranscriberDataModels(unittest.TestCase):

    def test_transcript_result_structure(self):
        words = [
            WordTimestamp(word="Hello", start=0.0, end=0.5),
            WordTimestamp(word="world", start=0.5, end=1.0)
        ]
        segment = TranscriptSegment(id=0, start=0.0, end=1.0, text="Hello world", words=words)
        result = TranscriptResult(text="Hello world", duration=1.0, segments=[segment], words=words)

        self.assertEqual(result.text, "Hello world")
        self.assertEqual(len(result.words), 2)
        self.assertEqual(result.words[0].word, "Hello")


class TestAnalyzerParsing(unittest.TestCase):

    def setUp(self):
        self.analyzer = ViralityAnalyzer(api_key="mock_key", provider="gemini")

    def test_parse_llm_json_response(self):
        mock_raw_response = """
        ```json
        {
            "summary": "High energy tech commentary.",
            "clips": [
                {
                    "start_time": 10.0,
                    "end_time": 40.0,
                    "virality_score": 92,
                    "hook_score": 95,
                    "retention_score": 90,
                    "headline": "The Future of AI",
                    "reasoning": "Strong opening hook with high narrative pacing.",
                    "hook_text": "Did you know AI is changing everything?",
                    "suggested_caption": "Check out this AI clip! #AI #Tech"
                }
            ]
        }
        ```
        """
        res = self.analyzer._parse_llm_json_response("Test Video", 120.0, mock_raw_response)
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.clips[0].virality_score, 92)
        self.assertEqual(res.clips[0].headline, "The Future of AI")
        self.assertEqual(res.clips[0].start_time, 10.0)
        self.assertEqual(res.clips[0].end_time, 40.0)


if __name__ == "__main__":
    unittest.main()
