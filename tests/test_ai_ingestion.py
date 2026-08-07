"""
tests/test_ai_ingestion.py - Comprehensive Unit & Integration Tests for Agent 02 (AI & Ingestion Specialist).
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import requests
from modules.watcher import YouTubeWatcher, VideoItem
from modules.downloader import MediaDownloader, DownloadResult
from modules.transcriber import WhisperTranscriber, TranscriptResult, TranscriptSegment, WordTimestamp, retry_with_backoff
from modules.analyzer import ViralityAnalyzer, ViralityAnalysisResult, ViralClipCandidate


class TestYouTubeWatcher(unittest.TestCase):

    def setUp(self):
        self.watcher = YouTubeWatcher(filter_shorts=True, filter_live=True)

    def test_extract_channel_id_direct(self):
        channel_id = "UC_x5XG1OV2P6uZZ5FSM9Ttw"
        result = self.watcher.extract_channel_id(channel_id)
        self.assertEqual(result, channel_id)

    def test_is_youtube_short_detection(self):
        self.assertTrue(YouTubeWatcher.is_youtube_short("https://www.youtube.com/shorts/abc123xyz"))
        self.assertTrue(YouTubeWatcher.is_youtube_short("https://www.youtube.com/watch?v=123", "Insane Hack #Shorts"))
        self.assertFalse(YouTubeWatcher.is_youtube_short("https://www.youtube.com/watch?v=123", "Full Podcast Episode 10"))

    def test_parse_rss_xml_with_shorts_filtering(self):
        sample_xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">
            <title>Test Channel</title>
            <entry>
                <id>yt:video:long_vid_1</id>
                <yt:videoId>long_vid_1</yt:videoId>
                <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
                <title>Long Form Podcast</title>
                <link rel="alternate" href="https://www.youtube.com/watch?v=long_vid_1"/>
            </entry>
            <entry>
                <id>yt:video:short_vid_2</id>
                <yt:videoId>short_vid_2</yt:videoId>
                <yt:channelId>UC_x5XG1OV2P6uZZ5FSM9Ttw</yt:channelId>
                <title>Quick Tip #Shorts</title>
                <link rel="alternate" href="https://www.youtube.com/shorts/short_vid_2"/>
            </entry>
        </feed>
        """
        videos = self.watcher._parse_rss_xml(sample_xml)
        self.assertEqual(len(videos), 2)
        self.assertFalse(videos[0].is_short)
        self.assertTrue(videos[1].is_short)


class TestTranscriberAndBackoff(unittest.TestCase):

    def test_retry_with_backoff_success(self):
        call_count = 0

        def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                resp = requests.Response()
                resp.status_code = 429
                raise requests.exceptions.HTTPError(response=resp)
            return "SUCCESS"

        result = retry_with_backoff(flaky_func, max_retries=3, initial_delay=0.01, jitter=False)
        self.assertEqual(result, "SUCCESS")
        self.assertEqual(call_count, 2)

    def test_whisper_json_parsing_with_time_offset(self):
        transcriber = WhisperTranscriber(api_key="mock_key", provider="groq")
        sample_json = {
            "text": "Testing chunk offset",
            "language": "en",
            "duration": 5.0,
            "segments": [
                {
                    "id": 0,
                    "start": 1.0,
                    "end": 4.0,
                    "text": "Testing chunk offset",
                    "words": [
                        {"word": "Testing", "start": 1.0, "end": 2.0},
                        {"word": "chunk", "start": 2.0, "end": 3.0},
                        {"word": "offset", "start": 3.0, "end": 4.0}
                    ]
                }
            ]
        }
        res = transcriber._parse_whisper_json(sample_json, time_offset=600.0)
        self.assertEqual(res.duration, 605.0)
        self.assertEqual(res.segments[0].start, 601.0)
        self.assertEqual(res.segments[0].end, 604.0)
        self.assertEqual(res.words[0].start, 601.0)
        self.assertEqual(res.words[0].word, "Testing")


class TestAnalyzerPromptTuning(unittest.TestCase):

    def setUp(self):
        self.analyzer = ViralityAnalyzer(api_key="mock_key", provider="gemini")

    def test_parse_llm_json_response_with_quotes(self):
        mock_raw_response = """
        ```json
        {
            "summary": "High energy tech commentary.",
            "clips": [
                {
                    "start_time": 10.0,
                    "end_time": 40.0,
                    "virality_score": 95,
                    "hook_score": 98,
                    "retention_score": 92,
                    "headline": "The Future of AI",
                    "reasoning": "Strong opening hook with high narrative pacing.",
                    "hook_text": "Did you know AI is changing everything?",
                    "quote_text": "We are looking at a 10x multiplier in efficiency.",
                    "suggested_caption": "Check out this AI clip! #AI #Tech",
                    "content_category": "technology"
                }
            ]
        }
        ```
        """
        res = self.analyzer._parse_llm_json_response("Test Video", 120.0, mock_raw_response)
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.clips[0].virality_score, 95)
        self.assertEqual(res.clips[0].quote_text, "We are looking at a 10x multiplier in efficiency.")
        self.assertEqual(res.clips[0].content_category, "technology")
        self.assertEqual(res.clips[0].start_time, 10.0)
        self.assertEqual(res.clips[0].end_time, 40.0)

    def test_timestamp_bounds_clamping(self):
        mock_raw_response = """
        {
            "summary": "Boundary test",
            "clips": [
                {
                    "start_time": -5.0,
                    "end_time": 250.0,
                    "virality_score": 85,
                    "hook_score": 80,
                    "retention_score": 90,
                    "headline": "Overbounds Clip",
                    "reasoning": "Test boundary conditions",
                    "hook_text": "Hook text",
                    "suggested_caption": "Caption"
                }
            ]
        }
        """
        res = self.analyzer._parse_llm_json_response("Test Video", 100.0, mock_raw_response)
        self.assertEqual(len(res.clips), 1)
        self.assertEqual(res.clips[0].start_time, 0.0)
        self.assertEqual(res.clips[0].end_time, 100.0)


if __name__ == "__main__":
    unittest.main()
