"""
modules/analyzer.py - Gemini & OpenAI Virality Analyzer & Hook Extractor for ClipIt.

Prompts LLMs (Gemini 1.5/2.0/3.6 Flash, GPT-4o) with timestamped transcripts to identify
high-retention viral 15-60s clip candidates with hook, retention, and virality scores.
"""

import json
import os
import re
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field


class ViralClipCandidate(BaseModel):
    start_time: float = Field(..., description="Clip start timestamp in seconds")
    end_time: float = Field(..., description="Clip end timestamp in seconds")
    virality_score: int = Field(..., ge=0, le=100, description="Overall virality rating (0-100)")
    hook_score: int = Field(..., ge=0, le=100, description="Opening hook punch score (0-100)")
    retention_score: int = Field(..., ge=0, le=100, description="Pacing and viewer retention score (0-100)")
    headline: str = Field(..., description="Catchy title for the viral clip")
    reasoning: str = Field(..., description="Explanation of why this clip will go viral")
    hook_text: str = Field(..., description="The exact opening sentence or hook line")
    suggested_caption: str = Field(..., description="Social media post caption with engaging hashtags")


class ViralityAnalysisResult(BaseModel):
    video_title: str
    video_duration: float
    clips: List[ViralClipCandidate] = Field(default_factory=list)
    summary: Optional[str] = None
    raw_response: Optional[str] = None


class ViralityAnalyzer:
    """LLM Virality Analyzer utilizing Gemini API or OpenAI API."""

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
        """Construct system instructions and structured prompt for virality extraction."""
        system_instruction = (
            "You are a master social media producer and virality algorithm expert specializing in "
            "TikTok, YouTube Shorts, and Instagram Reels content strategy. Your goal is to identify "
            "the top 1% most viral, high-retention 15-60 second clips from longer video transcripts."
        )

        user_prompt = f"""
VIDEO TITLE: "{video_title}"
TOTAL DURATION: {video_duration:.1f} seconds

TIMESTAMPED TRANSCRIPT:
{formatted_transcript}

TASK REQUIREMENTS:
1. Scan the transcript to identify up to {max_clips} standalone, highly engaging clip moments.
2. Ideal clip duration: 15 to 60 seconds (must have precise `start_time` and `end_time` matching the transcript timestamps).
3. Each clip candidate must be scored from 0 to 100 on:
   - `hook_score`: The punchiness of the first 3-5 seconds.
   - `retention_score`: How well it maintains interest throughout.
   - `virality_score`: Overall algorithm potential and shareability.
4. Output MUST be valid JSON adhering strictly to the JSON schema provided below. Do not include markdown codeblock wrappers or explanatory text outside the JSON.

JSON SCHEMA REQUIREMENT:
{{
  "summary": "Brief overall analysis of the video content",
  "clips": [
    {{
      "start_time": 12.5,
      "end_time": 45.0,
      "virality_score": 95,
      "hook_score": 92,
      "retention_score": 98,
      "headline": "Viral Clip Headline",
      "reasoning": "Why this clip hooks viewers immediately and holds retention.",
      "hook_text": "The exact opening line of the clip.",
      "suggested_caption": "Caption for social media #hashtag1 #hashtag2"
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
        """Call Google Gemini REST API to produce virality analysis."""
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
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }

        print(f"[Analyzer] Querying Gemini ({model_name}) for virality analysis...")
        try:
            resp = requests.post(url, json=payload, timeout=90)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"]
                return self._parse_llm_json_response(video_title, video_duration, raw_text)
            else:
                print(f"[Analyzer] Gemini API HTTP {resp.status_code}: {resp.text}")
                raise RuntimeError(f"Gemini API Error: {resp.text}")
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
        """Call OpenAI Chat Completions API as fallback."""
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
            "temperature": 0.3,
            "response_format": {"type": "json_object"}
        }

        print(f"[Analyzer] Querying OpenAI ({model_name}) for virality analysis...")
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=90)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data["choices"][0]["message"]["content"]
                return self._parse_llm_json_response(video_title, video_duration, raw_text)
            else:
                raise RuntimeError(f"OpenAI API Error HTTP {resp.status_code}: {resp.text}")
        except Exception as e:
            print(f"[Analyzer] OpenAI request failed: {e}")
            raise

    def _parse_llm_json_response(self, video_title: str, video_duration: float, raw_text: str) -> ViralityAnalysisResult:
        """Parse raw LLM JSON text into structured ViralityAnalysisResult."""
        cleaned_text = raw_text.strip()
        # Remove markdown fences if present
        if cleaned_text.startswith("```"):
            cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text)
            cleaned_text = re.sub(r"\s*```$", "", cleaned_text)

        try:
            parsed = json.loads(cleaned_text)
            summary = parsed.get("summary")
            clips_data = parsed.get("clips", [])

            clips: List[ViralClipCandidate] = []
            for c in clips_data:
                clips.append(ViralClipCandidate(
                    start_time=float(c.get("start_time", 0.0)),
                    end_time=float(c.get("end_time", 0.0)),
                    virality_score=int(c.get("virality_score", 50)),
                    hook_score=int(c.get("hook_score", 50)),
                    retention_score=int(c.get("retention_score", 50)),
                    headline=str(c.get("headline", "Viral Clip")),
                    reasoning=str(c.get("reasoning", "")),
                    hook_text=str(c.get("hook_text", "")),
                    suggested_caption=str(c.get("suggested_caption", ""))
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
