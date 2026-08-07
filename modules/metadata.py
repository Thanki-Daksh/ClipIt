"""
modules/metadata.py - Social Media Metadata Package Compiler for ClipIt.

Merges LLM-generated titles/descriptions/hashtags with account branding and
CTA into a metadata.json placed alongside the final .mp4 clip in the account
export folder (storage/accounts/{account_id}/outputs/).

Owned by Agent 03 (Media & Graphics Engineer). Do not edit by other agents.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from core.logger import get_logger

logger = get_logger("metadata")

DEFAULT_CTA = "Link in bio for the full guide!"


class MetadataCompiler:
    """
    Compiles the final output package per account profile.

    Accepts the virality-analysis fields (headline/title, suggested caption,
    hashtags) plus account branding, and writes metadata.json next to the
    rendered clip.
    """

    def __init__(self, storage_root: str = "storage/accounts") -> None:
        self.storage_root = os.path.abspath(storage_root)

    def compile(
        self,
        clip_id: str,
        video_file: str,
        caption_file: Optional[str] = None,
        account_id: str = "default",
        title: Optional[str] = None,
        description: Optional[str] = None,
        hashtags: Optional[List[str]] = None,
        cta: Optional[str] = None,
        hook_text: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build and persist the metadata package.

        Args:
            clip_id:      Unique clip identifier, e.g. "clip_acc01_001".
            video_file:   Path (relative or absolute) to the final .mp4.
            caption_file: Optional .ass subtitle file path.
            account_id:   Account key -> storage/accounts/{account_id}/outputs/.
            title:        Clip title (LLM headline fallback applied if missing).
            description:  Social post description.
            hashtags:     List of tags, each normalized to start with '#'.
            cta:          Call-to-action line; defaults to DEFAULT_CTA.
            hook_text:    Optional opening hook line.
            keywords:     Optional keyword list.
            extra:        Any additional fields to merge into the package.

        Returns the metadata dict (also persisted as metadata.json).
        """
        if not clip_id:
            raise ValueError("clip_id is required for metadata packaging.")
        if not video_file:
            raise ValueError("video_file is required for metadata packaging.")

        hashtags = self._normalize_hashtags(hashtags)

        metadata: Dict[str, Any] = {
            "clip_id": clip_id,
            "title": title or f"Clip {clip_id} 🚀",
            "description": description or self._default_description(title, hashtags),
            "hashtags": hashtags,
            "cta": cta or DEFAULT_CTA,
            "video_file": video_file,
            "caption_file": caption_file,
        }
        if hook_text:
            metadata["hook_text"] = hook_text
        if keywords:
            metadata["keywords"] = keywords
        if extra:
            metadata.update(extra)

        output_dir = self._output_dir(account_id)
        metadata_path = os.path.join(output_dir, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        logger.info("Wrote metadata package: %s", metadata_path)
        return metadata

    def _output_dir(self, account_id: str) -> str:
        """storage/accounts/{account_id}/outputs (created if missing)."""
        out = os.path.join(self.storage_root, account_id, "outputs")
        os.makedirs(out, exist_ok=True)
        return out

    @staticmethod
    def _normalize_hashtags(hashtags: Optional[List[str]]) -> List[str]:
        """Strip spaces and guarantee each tag starts with '#'."""
        if not hashtags:
            return []
        normalized: List[str] = []
        for tag in hashtags:
            t = str(tag).strip().lstrip("#").replace(" ", "")
            if t:
                normalized.append(f"#{t}")
        return normalized

    @staticmethod
    def _default_description(title: Optional[str], hashtags: List[str]) -> str:
        tag_str = " ".join(hashtags) if hashtags else "#shorts"
        base = title or "New clip"
        return f"{base} {tag_str}"