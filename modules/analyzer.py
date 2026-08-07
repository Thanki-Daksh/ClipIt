"""
modules/analyzer.py - Gemini & OpenAI Virality Analyzer & Hook Extractor for ClipIt.

Prompts LLMs (Gemini 1.5/2.0/3.6 Flash, GPT-4o) with timestamped transcripts to identify
high-retention viral 15-60s clip candidates with hook, retention, quote, and virality scores.
Includes exponential backoff retry client.
"""

import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field

from modules.transcriber import retry_with_backoff


class ViralClipCandidate(BaseModel):
    start_time: float = Field(..., description="Clip start timestamp in seconds")
    end_time: float = Field(..., description="Clip end timestamp in seconds")
    virality_score: int = Field(..., ge=0, le=100, description="Overall virality rating (0-100)")
    hook_score: int = Field(..., ge=0, le=100, description="Opening hook punch score (0-100)")
    retention_score: int = Field(..., ge=0, le=100, description="Pacing and viewer retention score (0-100)")
    headline: str = Field(..., description="Catchy title for the viral clip")
    reasoning: str = Field(..., description="Explanation of why this clip will go viral")
    hook_text: str = Field(..., description="The exact opening sentence or hook line")
    quote_text: str = Field(default="", description="The key highlight quote or memorable line in the clip")
    suggested_caption: str = Field(..., description="Social media post caption with engaging hashtags")
    content_category: str = Field(default="general", description="Category e.g. comedy, education, controversy, story")


class ViralityAnalysisResult(BaseModel):
    video_title: str
    video_duration: float
    clips: List[ViralClipCandidate] = Field(default_factory=list)
    summary: Optional[str] = None
    raw_response: Optional[str] = None


class ViralityAnalyzer:
    """LLM Virality Analyzer utilizing Gemini API or OpenAI API with prompt tuning & backoff."""

    GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", config_path: str = "config.json"):
        self.provider = provider.lower()
        self.api_key = api_key or self._load_api_key_from_env_or_config(config_path)
        if not self.api_key:
            print(f"[Analyzer] WARNING: No API key found for provider '{self.provider}'. Set GEMINI_API_KEY / OPENAI_API_KEY or update config.json.")

    def _load_api_key_from_env_or_config(self, config_path: str) -> Optional[str]:
        """Load API key from environment or config.json."""
        if self.provider == "gemini":
            env_key = os.getenv("GEMINI_API_KEY")
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
                    return cfg.get("gemini_api_key" if self.provider == "gemini" else "openai_api_key")
            except Exception as e:
                print(f"[Analyzer] Error reading config file: {e}")
        return None

    def analyze_transcript(
        self,
        video_title: str,
        video_duration: float,
        transcript_segments: List[Any],
        max_clips: int = 5,
        model_name: Optional[str] = None
    ) -> ViralityAnalysisResult:
        """Analyze timestamped transcript segments and return candidate viral clips."""

        # Format transcript segments for prompt
        formatted_transcript_lines = []
        for seg in transcript_segments:
            start = getattr(seg, "start", seg.get("start") if isinstance(seg, dict) else 0.0)
            end = getattr(seg, "end", seg.get("end") if isinstance(seg, dict) else 0.0)
            text = getattr(seg, "text", seg.get("text") if isinstance(seg, dict) else "")
            formatted_transcript_lines.append(f"[{start:.2f}s -> {end:.2f}s]: {text}")

        formatted_transcript = "\n".join(formatted_transcript_lines)

        system_instruction, user_prompt = self._build_prompts(
            video_title=video_title,
            video_duration=video_duration,
            formatted_transcript=formatted_transcript,
            max_clips=max_clips
        )

        if self.provider == "gemini":
            return self._call_gemini_api(
                video_title=video_title,
                video_duration=video_duration,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                model_name=model_name or "gemini-1.5-flash"
            )
        else:
            return self._call_openai_api(
                video_title=video_title,
                video_duration=video_duration,
                system_instruction=system_instruction,
                user_prompt=user_prompt,
                model_name=model_name or "gpt-4o"
            )

    def _build_prompts(self, video_title: str, video_duration: float, formatted_transcript: str, max_clips: int) -> tuple[str, str]:
        """Construct system instructions and tuned prompt for virality & quote extraction."""
        system_instruction = (
            "You are an elite short-form content producer and virality scientist specializing in "
            "TikTok, YouTube Shorts, and Instagram Reels content strategy. Your mission is to extract "
            "the top 1% highest-converting, viral moments (15-60s) from long-form video transcripts. "
            "Every clip must have a powerful opening hook line, clear standalone story/payoff, and exact quote."
        )

        user_prompt = f"""
VIDEO TITLE: "{video_title}"
TOTAL DURATION: {video_duration:.1f} seconds

TIMESTAMPED TRANSCRIPT:
{formatted_transcript}

VIRALITY ANALYSIS RULES:
1. Identify up to {max_clips} standalone clip segments (duration MUST be between 15.0s and 60.0s).
2. Ensure `start_time` and `end_time` match exact transcript timestamps and do NOT exceed total video duration ({video_duration:.1f}s).
3. Score each clip (0-100) on:
   - `hook_score`: Immediate visual/verbal hook strength (first 3-5 seconds).
   - `retention_score`: Narrative pacing and emotional engagement payload.
   - `virality_score`: Overall algorithm potential and shareability.
4. Extract the exact `hook_text` (opening sentence) and `quote_text` (memorable highlight quote).
5. Output strictly formatted JSON matching the exact schema below without markdown formatting or surrounding explanation.

JSON SCHEMA:
{{
  "summary": "High-level summary of video content and virality opportunities",
  "clips": [
    {{
      "start_time": 12.5,
      "end_time": 45.0,
      "virality_score": 96,
      "hook_score": 94,
      "retention_score": 98,
      "headline": "Insane AI Revelation",
      "reasoning": "Starts with a massive pattern interrupt question and delivers an immediate payload.",
      "hook_text": "Did you know AI models can now reason faster than humans?",
      "quote_text": "We are looking at a 10x multiplier in efficiency.",
      "suggested_caption": "This changes everything! 🚀 #AI #Tech #Mindblown",
      "content_category": "technology"
    }}
  ]
}}
"""
        return system_instruction, user_prompt

    def _call_gemini_api(
        self,
        video_title: str,
        video_duration: float,
        system_instruction: str,
        user_prompt: str,
        model_name: str
    ) -> ViralityAnalysisResult:
        """Call Google Gemini REST API with exponential backoff."""
        if not self.api_key:
            raise ValueError("Missing GEMINI_API_KEY for Gemini provider.")

        url = f"{self.GEMINI_BASE_URL}/{model_name}:generateContent?key={self.api_key}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{system_instruction}\n\n{user_prompt}"}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }

        print(f"[Analyzer] Querying Gemini ({model_name}) with exponential backoff...")

        def _request():
            resp = requests.post(url, json=payload, timeout=90)
            resp.raise_for_status()
            return resp.json()

        try:
            data = retry_with_backoff(_request, max_retries=4, initial_delay=3.0)
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._parse_llm_json_response(video_title, video_duration, raw_text)
        except Exception as e:
            print(f"[Analyzer] Gemini request failed: {e}")
            raise

    def _call_openai_api(
        self,
        video_title: str,
        video_duration: float,
        system_instruction: str,
        user_prompt: str,
        model_name: str
    ) -> ViralityAnalysisResult:
        """Call OpenAI Chat Completions API with exponential backoff."""
        if not self.api_key:
            raise ValueError("Missing OPENAI_API_KEY for OpenAI provider.")

        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"}
        }

        print(f"[Analyzer] Querying OpenAI ({model_name}) with exponential backoff...")

        def _request():
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
            resp.raise_for_status()
            return resp.json()

        try:
            data = retry_with_backoff(_request, max_retries=4, initial_delay=3.0)
            raw_text = data["choices"][0]["message"]["content"]
            return self._parse_llm_json_response(video_title, video_duration, raw_text)
        except Exception as e:
            print(f"[Analyzer] OpenAI request failed: {e}")
            raise

    def _parse_llm_json_response(self, video_title: str, video_duration: float, raw_text: str) -> ViralityAnalysisResult:
        """Parse raw LLM JSON text into structured ViralityAnalysisResult with timestamp bounds clamping."""
        cleaned_text = raw_text.strip()
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text)
            cleaned_text = re.sub(r"\s*```$", "", cleaned_text)

        try:
            parsed = json.loads(cleaned_text)
            summary = parsed.get("summary")
            clips_data = parsed.get("clips", [])

            clips: List[ViralClipCandidate] = []
            for c in clips_data:
                start_t = max(0.0, float(c.get("start_time", 0.0)))
                end_t = float(c.get("end_time", 0.0))
                if video_duration > 0 and end_t > video_duration:
                    end_t = video_duration

                if end_t <= start_t:
                    continue  # Invalid clip bounds

                clips.append(ViralClipCandidate(
                    start_time=start_t,
                    end_time=end_t,
                    virality_score=min(100, max(0, int(c.get("virality_score", 50)))),
                    hook_score=min(100, max(0, int(c.get("hook_score", 50)))),
                    retention_score=min(100, max(0, int(c.get("retention_score", 50)))),
                    headline=str(c.get("headline", "Viral Clip")),
                    reasoning=str(c.get("reasoning", "")),
                    hook_text=str(c.get("hook_text", "")),
                    quote_text=str(c.get("quote_text", "")),
                    suggested_caption=str(c.get("suggested_caption", "")),
                    content_category=str(c.get("content_category", "general"))
                ))

            # Sort clips by virality_score descending
            clips.sort(key=lambda x: x.virality_score, reverse=True)

            return ViralityAnalysisResult(
                video_title=video_title,
                video_duration=video_duration,
                clips=clips,
                summary=summary,
                raw_response=raw_text
            )
        except json.JSONDecodeError as e:
            print(f"[Analyzer] Failed to parse JSON response: {e}. Raw response:\n{raw_text}")
            return ViralityAnalysisResult(
                video_title=video_title,
                video_duration=video_duration,
                clips=[],
                summary="Failed to parse structured JSON from LLM.",
                raw_response=raw_text
            )
