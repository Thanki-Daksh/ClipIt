"""
modules/captioner.py - ASS Animated Subtitle Generator & Burn-In Renderer for ClipIt.

Generates Advanced SubStation Alpha (.ass) files with word-by-word active
highlight (BGR color codes) and burns them onto vertical clips via the
`subtitles` FFmpeg filter without audio sync drift.

Supports three built-in style presets: VIRAL_YELLOW, MINIMAL_WHITE, NEON_CYAN.

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
Style: Default, {font_name}, {font_size}, {primary}, {secondary}, {outline}, {back}, -1, 0, 0, 0, 100, 100, 0, 0, 1, 4, 2, 2, 80, 80, 480

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# ---- Built-in style presets ------------------------------------------- #
# Each preset maps a name to (primary, secondary/highlight, outline, back,
# font_name, font_size). Secondary colour is the active-word highlight.
# Spec-era aliases: TIKTOK_YELLOW == VIRAL_YELLOW, CLEAN_WHITE == MINIMAL_WHITE.
ASS_PRESETS = {
    "VIRAL_YELLOW": {
        "primary": ASS_WHITE,
        "highlight": ASS_YELLOW,
        "outline": ASS_BLACK_OUTLINE,
        "back": ASS_DARK_BACK,
        "font_name": "Montserrat ExtraBold",
        "font_size": 64,
    },
    "TIKTOK_YELLOW": {
        "primary": ASS_WHITE,
        "highlight": ASS_YELLOW,
        "outline": ASS_BLACK_OUTLINE,
        "back": ASS_DARK_BACK,
        "font_name": "Montserrat ExtraBold",
        "font_size": 64,
    },
    "MINIMAL_WHITE": {
        "primary": ASS_WHITE,
        "highlight": ASS_WHITE,
        "outline": "&H00333333",
        "back": "&H00000000",
        "font_name": "Arial",
        "font_size": 56,
    },
    "CLEAN_WHITE": {
        "primary": ASS_WHITE,
        "highlight": ASS_WHITE,
        "outline": "&H00333333",
        "back": "&H00000000",
        "font_name": "Arial",
        "font_size": 56,
    },
    "NEON_CYAN": {
        "primary": "&H00FFFFFF",
        "highlight": ASS_CYAN,
        "outline": "&H00141414",
        "back": "&H66000000",
        "font_name": "Montserrat ExtraBold",
        "font_size": 68,
    },
}

# ---- Font fallback engine (TSK-A03-11) -------------------------------- #
# libass falls back to an OS default when a named font is missing, which
# silently changes the look. We probe common system font dirs and pick the
# first installed family: Montserrat ExtraBold -> Montserrat -> Inter -> Arial.
FONT_DIRS = [
    r"C:\Windows\Fonts",
    "/usr/share/fonts",
    "/usr/local/share/fonts",
    "/System/Library/Fonts",
]
FONT_FALLBACK_CHAIN = ["Montserrat ExtraBold", "Montserrat", "Inter", "Arial"]


class ASSSubtitleGenerator:
    """
    Converts a word-timestamp array into an .ass file with active words
    highlighted. Words are chunked into short dialogue lines; inside each line,
    the currently-spoken word is wrapped in a temporary color override and then
    reset, producing the 'active word' karaoke effect.
    """

    def __init__(
        self,
        font_name: str = "Montserrat ExtraBold",
        font_size: int = 64,
        preset: Optional[str] = None,
    ) -> None:
        if preset:
            spec = ASS_PRESETS.get(str(preset).upper())
            if spec is None:
                raise ValueError(
                    f"Unknown ASS preset '{preset}'. "
                    f"Available: {', '.join(ASS_PRESETS)}"
                )
            self.preset_name = str(preset).upper()
            self.font_name = self.resolve_font(spec["font_name"])
            self.font_size = spec["font_size"]
            self.primary = spec["primary"]
            self.highlight = spec["highlight"]
            self.outline = spec["outline"]
            self.back = spec["back"]
        else:
            self.preset_name = None
            self.font_name = self.resolve_font(font_name)
            self.font_size = font_size
            self.primary = ASS_WHITE
            self.highlight = ASS_YELLOW
            self.outline = ASS_BLACK_OUTLINE
            self.back = ASS_DARK_BACK
        logger.info(
            "Subtitle style ready: preset=%s font=%s (fallback-resolved)",
            self.preset_name or "custom", self.font_name,
        )

    # ------------------------------------------------------------------
    # Font fallback engine (TSK-A03-11)
    # ------------------------------------------------------------------
    @classmethod
    def available_fonts(cls) -> set:
        """Return the set of lowercased font file stems installed on the host."""
        stems: set = set()
        for d in FONT_DIRS:
            if not os.path.isdir(d):
                continue
            try:
                for name in os.listdir(d):
                    low = name.lower()
                    if low.endswith((".ttf", ".otf", ".ttc")):
                        stems.add(os.path.splitext(name)[0].lower())
            except OSError:
                continue
        return stems

    @classmethod
    def resolve_font(cls, preferred: str = "Montserrat ExtraBold") -> str:
        """
        Pick the first installed font family from the fallback chain,
        preferring the requested family. Never returns a missing font:
        guaranteed terminal fallback is 'Arial' (universally installed).
        """
        avail = cls.available_fonts()
        if avail:
            for cand in [preferred, *FONT_FALLBACK_CHAIN]:
                stem = cand.split()[0].lower()
                if any(stem in name for name in avail):
                    return cand
        return "Arial"

    def generate_ass(
        self,
        words: List[Dict[str, Any]],
        output_ass_path: str,
        chunk_size: int = 4,
        highlight_color: Optional[str] = None,
        base_color: Optional[str] = None,
        primary: Optional[str] = None,
        outline: Optional[str] = None,
        back: Optional[str] = None,
    ) -> str:
        """
        Write an .ass file from a list of word dicts.

        Each word dict expects keys: 'word', 'start' (sec), 'end' (sec).
        Optionally 'text' / 'start_time' keys are tolerated for interop.

        When the generator was built with a ``preset``, the preset's palette
        is used unless explicitly overridden here.

        Returns the output path.
        """
        if not words:
            raise ValueError("Cannot generate ASS subtitles from an empty word list.")

        normalized = self._normalize_words(words)
        if sum(1 for w in normalized if w["text"].strip()) == 0:
            raise ValueError("No non-empty subtitle words provided.")

        pc = primary or self.primary
        oc = outline or self.outline
        bc = back or self.back
        hl = highlight_color or self.highlight
        base = base_color or pc

        lines = [ASS_HEADER.format(
            font_name=self.font_name, font_size=self.font_size,
            primary=pc, secondary=hl, outline=oc, back=bc,
        )]

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
                text_parts.append(f"{{\\c{hl}&}}{w}{{\\c{base}&}}")

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

    def __init__(
        self,
        ffmpeg: str = "ffmpeg",
        ffprobe: str = "ffprobe",
        timeout: int = 120,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.ffprobe = ffprobe
        self.timeout = timeout        # TSK-A03-15: hard cap on burn-in renders.

    def burn_subtitles(
        self,
        video_path: str,
        ass_path: str,
        output_path: str,
        crf: int = 20,
        preset: str = "fast",
        delete_intermediate: bool = False,
        timeout: Optional[float] = None,  # seconds; hung FFmpeg burn is killed (TSK-A06-09)
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
        try:
            result = subprocess.run(
                cmd, cwd=ass_dir, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                check=False,
                timeout=timeout if timeout is not None else self.timeout,
            )
        except subprocess.TimeoutExpired:
            limit = timeout if timeout is not None else self.timeout
            logger.error("Subtitle burn timed out after %ss (process terminated)", limit)
            raise RuntimeError(
                f"Subtitle burn-in timed out after {limit}s — the hung child "
                f"process was terminated."
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