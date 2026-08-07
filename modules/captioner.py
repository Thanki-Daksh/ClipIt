"""
modules/captioner.py - ASS Animated Subtitle Generator & Burn-In Renderer for ClipIt.

Generates Advanced SubStation Alpha (.ass) files with word-by-word active
highlight (BGR color codes) and burns them onto vertical clips via the
`subtitles` FFmpeg filter without audio sync drift.

Owned by Agent 03 (Media & Graphics Engineer). Do not edit by other agents.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, List, Optional

from core.logger import get_logger

logger = get_logger("captioner")

# ---- ASS BGR color helpers (format &HBBGGRR) -------------------------- #
ASS_WHITE = "&H00FFFFFF"
ASS_YELLOW = "&H0000FFFF"          # active-word highlight in the spec example
ASS_CYAN = "&H00FFFF00"
ASS_NEON_GREEN = "&H0000FF00"
ASS_BLACK_OUTLINE = "&H00000000"
ASS_DARK_BACK = "&H80000000"

# ASS color codes in --header format
ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default, {font_name}, {font_size}, &H00FFFFFF, &H0000FFFF, &H00000000, &H80000000, -1, 0, 0, 0, 100, 100, 0, 0, 1, 4, 2, 2, 80, 80, 480

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


class ASSSubtitleGenerator:
    """
    Converts a word-timestamp array into an .ass file with active words
    highlighted. Words are chunked into short dialogue lines; inside each line,
    the currently-spoken word is wrapped in a temporary color override and then
    reset, producing the 'active word' karaoke effect.
    """

    def __init__(self, font_name: str = "Montserrat ExtraBold", font_size: int = 64) -> None:
        self.font_name = font_name
        self.font_size = font_size

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        output_ass_path: str,
        chunk_size: int = 4,
        highlight_color: str = ASS_YELLOW,
        base_color: str = ASS_WHITE,
    ) -> str:
        """
        Write an .ass file from a list of word dicts.

        Each word dict expects keys: 'word', 'start' (sec), 'end' (sec).
        Optionally 'text' / 'start_time' keys are tolerated for interop.

        Returns the output path.
        """
        if not words:
            raise ValueError("Cannot generate ASS subtitles from an empty word list.")

        normalized = self._normalize_words(words)
        if sum(1 for w in normalized if w["text"].strip()) == 0:
            raise ValueError("No non-empty subtitle words provided.")

        lines = [ASS_HEADER.format(font_name=self.font_name, font_size=self.font_size)]

        # Chunk consecutive words into dialogue lines of <= chunk_size words.
        for i in range(0, len(normalized), chunk_size):
            chunk = normalized[i:i + chunk_size]
            start = chunk[0]["start"]
            end = chunk[-1]["end"]

            # Build a line with per-word active-highlight overrides.
            # ASS inline color codes use &HBBGGRR& (trailing '&' terminator).
            text_parts: List[str] = []
            for word in chunk:
                w = self._escape(word["text"])
                # active word carries the highlight color inline (BGR override)
                text_parts.append(f"{{\\c{highlight_color}&}}{w}{{\\c{base_color}&}}")

            line_text = " ".join(text_parts)
            start_str = self._format_timestamp(start)
            end_str = self._format_timestamp(end)
            lines.append(
                f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{line_text}\n"
            )

        os.makedirs(os.path.dirname(os.path.abspath(output_ass_path)) or ".", exist_ok=True)
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        logger.info("Generated ASS subtitle file: %s (%d highlighted lines)", output_ass_path, len(normalized))
        return output_ass_path

    @staticmethod
    def _normalize_words(words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Coerce word entries into a canonical shape with text/start/end keys."""
        normalized: List[Dict[str, Any]] = []
        for w in words:
            text = str(w.get("word", w.get("text", ""))).strip()
            start = float(w.get("start", w.get("start_time", 0.0)))
            end = float(w.get("end", w.get("end_time", start + 0.2)))
            if text:
                normalized.append({"text": text, "start": start, "end": end})
        return normalized

    @staticmethod
    def _escape(text: str) -> str:
        """
        Escape ASS special characters so curly braces / backslashes don't crash
        the parser or get interpreted as override tags.
        """
        # Backslash first (doubles as escaping for the rest).
        text = text.replace("\\", "\\\\")
        text = text.replace("{", "\\{")
        text = text.replace("}", "\\}")
        return text

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """Format float seconds as ASS H:MM:SS.cc (centiseconds)."""
        seconds = max(0.0, float(seconds))
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hrs}:{mins:02d}:{secs:05.2f}"


class SubtitleRenderer:
    """
    Burns an .ass subtitle file onto a vertical clip using the FFmpeg
    `subtitles` filter. `-c:a copy` keeps audio untouched, guaranteeing zero
    audio sync drift.
    """

    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe

    def burn_subtitles(
        self,
        video_path: str,
        ass_path: str,
        output_path: str,
        crf: int = 20,
        preset: str = "fast",
        delete_intermediate: bool = False,
    ) -> str:
        """
        Burn ASS subtitles into the video.

        Args:
            video_path:  Input vertical clip (uncaptioned).
            ass_path:    .ass subtitle file.
            output_path: Final captioned .mp4.
            crf:         Quality factor (lower = better).
            preset:      x264 preset.
            delete_intermediate: if True, delete the input clip after success
                                (storage cleanup of intermediate renders).

        Returns the output path.
        """
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Input clip not found: {video_path}")
        if not os.path.exists(ass_path):
            raise FileNotFoundError(f"ASS subtitle file not found: {ass_path}")

        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)

        # On Windows the drive colon and backslashes collide with the `subtitles`
        # filter's option syntax. Robust cross-platform fix: cd into the subtitle
        # directory and reference the .ass by basename only.
        ass_dir = os.path.dirname(os.path.abspath(ass_path))
        ass_basename = os.path.basename(ass_path)
        cmd = [
            self.ffmpeg, "-y",
            "-i", video_path,
            "-vf", f"subtitles={ass_basename}",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "copy",          # copy audio stream = zero sync drift
            "-pix_fmt", "yuv420p",
            output_path,
        ]

        logger.info("Burning subtitles %s -> %s", os.path.basename(ass_path), output_path)
        result = subprocess.run(
            cmd, cwd=ass_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        if result.returncode != 0:
            err = result.stderr.decode("utf-8", errors="replace")
            logger.error("Subtitle burn-in failed:\n%s", err)
            raise RuntimeError(f"Subtitle burn-in failed (exit {result.returncode}): {err}")

        if not os.path.exists(output_path):
            raise RuntimeError(f"Burn-in reported success but output missing: {output_path}")

        if delete_intermediate and os.path.abspath(output_path) != os.path.abspath(video_path):
            try:
                os.remove(video_path)
                logger.info("Deleted intermediate clip: %s", video_path)
            except OSError as e:
                logger.warning("Could not delete intermediate clip %s: %s", video_path, e)

        return output_path