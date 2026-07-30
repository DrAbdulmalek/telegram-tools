"""Media description helpers (no Telethon dependency — pure formatting)."""

from __future__ import annotations

from typing import Any


def format_size(size_bytes: int) -> str:
    """Human-readable file size."""
    if not size_bytes:
        return "0 B"
    units = ["B", "KB", "MB", "GB"]
    size = float(size_bytes)
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {units[idx]}"


def describe_media(message: Any) -> str:
    """Return a short description of a message's media type."""
    try:
        from telethon.tl.types import (
            MessageMediaDocument,
            MessageMediaPhoto,
            MessageMediaWebPage,
        )
    except ImportError:
        return "Media"

    media = getattr(message, "media", None)
    if not media:
        text = (getattr(message, "text", "") or "")[:40]
        return f"Text: {text}" if text else "Empty"

    if isinstance(media, MessageMediaPhoto):
        return "Photo"

    if isinstance(media, MessageMediaDocument) and media.document:
        mime = media.document.mime_type or ""
        size = (
            media.document.size / (1024 * 1024)
            if media.document.size
            else 0
        )
        if "video" in mime:
            return f"Video ({size:.1f} MB)"
        if "audio" in mime:
            return f"Audio ({size:.1f} MB)"
        return f"File ({size:.1f} MB)"

    if isinstance(media, MessageMediaWebPage):
        return "Link"

    return "Media"
