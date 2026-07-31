"""
TelegramCopier — Fast bulk copy between channels (v1.2 — preview + dedup).

Strategy: re-send the original media directly via ``send_message(file=media)``.
This avoids downloading + re-uploading, so it's much faster than the
forwarder. The trade-off: it cannot bypass "Restrict Saving Content".

Use cases:
  - Public source channels
  - Private channels where you have posting rights
  - Quick mirroring / backup

v1.2 additions
--------------
- **preview_messages(config)**: fetch a list of ``CopyPreview`` rows (id, date,
  snippet, has_media, media_type, media_size, dup_status) WITHOUT sending
  anything. Used to populate the preview grid in the UI.
- **scan_dest_duplicates(dest, source_previews)**: walk the destination channel
  once and compute a set of content hashes already present there, so each
  source message can be marked as duplicate / unique before the user picks.
- **compute_message_hash(message)**: deterministic SHA-256 of message content.
  For text-only messages: hash of normalized text. For media: hash of file
  properties (size + name + mime). Two messages with identical content
  produce identical hashes regardless of where they live.
- **copy(config)** now honors ``skip_duplicates`` and ``selected_ids`` — only
  sends the messages the user explicitly selected, and skips any whose hash
  already exists in the destination.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from telethon.errors import (
    ChatWriteForbiddenError,
    DocumentInvalidError,
    FloodWaitError,
    PhotoInvalidError,
)
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
)

# FileReferenceError was renamed in Telethon 1.40+
try:
    from telethon.errors import FileReferenceExpiredError as FileReferenceError
except ImportError:
    try:
        from telethon.errors import FileReferenceError
    except ImportError:
        FileReferenceError = Exception  # fallback — broad catch

from .base import TelegramClientMixin
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


# ─── Preview & Dedup ─────────────────────────────────────────────────────────


@dataclass
class CopyPreview:
    """A preview entry shown to the user before the actual copy.

    ``dup_status`` is one of:
      - "unknown"   — destination not scanned yet
      - "duplicate" — same content already exists in destination
      - "unique"    — not found in destination
    """

    message_id: int
    date: str  # ISO format
    text_snippet: str
    has_media: bool
    media_type: str  # photo | document | none
    media_size_mb: float = 0.0
    media_name: str = ""
    content_hash: str = ""
    dup_status: str = "unknown"  # unknown | duplicate | unique
    selected: bool = True

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "date": self.date,
            "text_snippet": self.text_snippet,
            "has_media": self.has_media,
            "media_type": self.media_type,
            "media_size_mb": round(self.media_size_mb, 2),
            "media_name": self.media_name,
            "content_hash": self.content_hash,
            "dup_status": self.dup_status,
            "selected": self.selected,
        }


def _normalize_text(text: str) -> str:
    """Normalize text for stable hashing: collapse whitespace, lowercase."""
    if not text:
        return ""
    # Collapse all whitespace (incl. newlines) to single spaces
    return re.sub(r"\s+", " ", text.strip()).lower()


def compute_message_hash(message: Any) -> str:
    """Compute a deterministic SHA-256 hash for a Telethon message.

    For text-only messages: hash of normalized text.
    For media messages: hash of (file_size, file_name, mime_type, normalized caption).
    Two messages with identical content produce identical hashes.
    """
    text_part = _normalize_text(message.text or "")

    media = getattr(message, "media", None)
    if media and not isinstance(media, MessageMediaWebPage):
        # Extract stable file properties
        size = 0
        name = ""
        mime = ""
        if isinstance(media, MessageMediaDocument) and media.document:
            size = int(getattr(media.document, "size", 0) or 0)
            mime = getattr(media.document, "mime_type", "") or ""
            for attr in getattr(media.document, "attributes", []) or []:
                # DocumentAttributeFilename has .file_name
                file_name = getattr(attr, "file_name", None)
                if file_name:
                    name = file_name
                    break
        elif isinstance(media, MessageMediaPhoto) and media.photo:
            # Photo: use the largest size as a proxy
            sizes = getattr(media.photo, "sizes", []) or []
            if sizes:
                last = sizes[-1]
                size = int(getattr(last, "size", 0) or 0)
            name = "photo.jpg"
            mime = "image/jpeg"

        hash_input = f"media|{size}|{name}|{mime}|{text_part}"
    else:
        hash_input = f"text|{text_part}"

    return hashlib.sha256(hash_input.encode("utf-8")).hexdigest()[:16]


# ─── Config & Result ─────────────────────────────────────────────────────────


@dataclass
class CopierConfig:
    """Configuration for a copy operation.

    v1.2 fields:
      - ``skip_duplicates``: if True, skip messages whose hash matches one
        already in the destination. Requires ``_dest_hashes`` to be populated
        by ``scan_dest_duplicates()`` before calling ``copy()``.
      - ``selected_ids``: optional list of source message IDs to copy. If None,
        copy everything (subject to other filters). If set, ONLY those IDs are
        copied — this is how the user's preview selections are honored.
    """

    source_channel: str
    dest_channel: str
    limit: int = 0  # 0 = unlimited
    delay: float = 3.0
    copy_text: bool = True
    copy_media: bool = True
    files_only: bool = False  # alias for copy_text=False
    reverse_order: bool = True  # oldest first
    min_id: int | None = None  # resume support
    max_id: int | None = None
    # v1.2
    skip_duplicates: bool = False
    selected_ids: list[int] | None = None


@dataclass
class CopierResult:
    """Outcome of a copy operation."""

    total: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    media_count: int = 0
    text_count: int = 0
    duplicates_skipped: int = 0  # v1.2: count of skipped dupes
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    last_source_id: int = 0

    @property
    def elapsed(self) -> str:
        secs = int(time.time() - self.start_time)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "copied": self.copied,
            "skipped": self.skipped,
            "failed": self.failed,
            "media": self.media_count,
            "text": self.text_count,
            "duplicates_skipped": self.duplicates_skipped,
            "cancelled": self.cancelled,
            "elapsed": self.elapsed,
            "last_source_id": self.last_source_id,
            "errors": self.errors[-10:],
        }


class TelegramCopier(TelegramClientMixin):
    """Fast channel-to-channel copier using direct media re-send.

    v1.2: adds preview, dedup, and selective copy.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "copier",
        session_string: str | None = None,
        progress_file: Path | None = None,
    ):
        super().__init__(api_id, api_hash, session_name, session_string)
        self.progress_file = progress_file or Path("copier_progress.json")
        self._cancelled = False
        # v1.2: cache of destination content hashes — populated by
        # scan_dest_duplicates() and consumed by copy() when skip_duplicates=True
        self._dest_hashes: set[str] = set()

    # ── Public API ──────────────────────────────────────────

    def cancel(self) -> None:
        self._cancelled = True

    def load_progress(self) -> dict:
        if self.progress_file.exists():
            try:
                return json.loads(self.progress_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"copied": 0, "skipped": 0, "failed": 0, "last_source_id": 0}

    def save_progress(self, data: dict) -> None:
        try:
            self.progress_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to save progress: {e}")

    # ── v1.2: Preview ──────────────────────────────────────

    async def preview_messages(
        self, config: CopierConfig, limit: int = 200
    ) -> list[CopyPreview]:
        """Fetch a preview list of source messages — NO sending happens.

        Args:
            config: CopierConfig (source_channel is required; dest_channel
                is only used when ``scan_dest_duplicates`` is called next).
            limit: max number of messages to preview (capped at 500 to keep
                the UI snappy).

        Returns:
            list of CopyPreview objects, oldest-first by default.
        """
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated — call send_code/verify_code first")

        limit = max(1, min(int(limit), 500))

        try:
            source = await self._resolve_entity(config.source_channel)
        except Exception as e:
            raise RuntimeError(f"Cannot access source channel: {e}") from e

        iter_kwargs: dict[str, Any] = {"reverse": config.reverse_order, "limit": limit}
        if config.min_id:
            iter_kwargs["min_id"] = config.min_id
        if config.max_id:
            iter_kwargs["max_id"] = config.max_id

        previews: list[CopyPreview] = []
        media_type_map = {
            MessageMediaPhoto: "photo",
            MessageMediaDocument: "document",
        }

        async for message in self.client.iter_messages(source, **iter_kwargs):
            # Skip empty messages
            if not message.text and not message.media:
                continue

            has_media = bool(message.media) and not isinstance(
                message.media, MessageMediaWebPage
            )
            # Apply same filters as copy()
            if (config.files_only or not config.copy_text) and not has_media:
                continue
            if not config.copy_media and has_media and not message.text:
                continue

            media_type = "none"
            size_mb = 0.0
            media_name = ""
            if has_media:
                media_type = media_type_map.get(type(message.media), "media")
                size_mb, media_name = self._extract_media_info(message)

            text = (message.text or "").strip()
            snippet = (text[:80] + "…") if len(text) > 80 else text
            if not snippet and has_media:
                snippet = f"({media_type}: {media_name or 'untitled'})"

            content_hash = compute_message_hash(message)

            # Mark duplicate if dest scan was already done
            dup_status = (
                "duplicate" if content_hash in self._dest_hashes
                else ("unique" if self._dest_hashes else "unknown")
            )

            previews.append(CopyPreview(
                message_id=message.id,
                date=message.date.isoformat() if message.date else "",
                text_snippet=snippet or "(no text)",
                has_media=has_media,
                media_type=media_type,
                media_size_mb=size_mb,
                media_name=media_name,
                content_hash=content_hash,
                dup_status=dup_status,
                selected=True,
            ))

        return previews

    @staticmethod
    def _extract_media_info(message: Any) -> tuple[float, str]:
        """Return (size_mb, file_name) for a message's media."""
        try:
            media = message.media
            if isinstance(media, MessageMediaDocument) and media.document:
                size = int(getattr(media.document, "size", 0) or 0)
                size_mb = round(size / (1024 * 1024), 2)
                name = ""
                for attr in getattr(media.document, "attributes", []) or []:
                    fn = getattr(attr, "file_name", None)
                    if fn:
                        name = fn
                        break
                return size_mb, name
            if isinstance(media, MessageMediaPhoto) and media.photo:
                sizes = getattr(media.photo, "sizes", []) or []
                if sizes:
                    last = sizes[-1]
                    size = int(getattr(last, "size", 0) or 0)
                    return round(size / (1024 * 1024), 2), "photo.jpg"
                return 0.0, "photo.jpg"
        except Exception:
            pass
        return 0.0, ""

    # ── v1.2: Destination duplicate scan ────────────────────

    async def scan_dest_duplicates(
        self, dest_channel: str, limit: int = 0
    ) -> dict:
        """Walk the destination channel and cache content hashes.

        Call this BEFORE preview_messages() to populate ``_dest_hashes`` so
        that preview rows are auto-tagged with dup_status='duplicate'.

        Args:
            dest_channel: channel identifier (username, ID, or t.me link).
            limit: max messages to scan. 0 = all (be careful with big channels).

        Returns:
            dict with: {scanned, unique_hashes, elapsed_seconds}
        """
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated — call send_code/verify_code first")

        try:
            dest = await self._resolve_entity(dest_channel)
        except Exception as e:
            raise RuntimeError(f"Cannot access destination channel: {e}") from e

        start = time.time()
        scanned = 0
        self._dest_hashes = set()

        iter_kwargs: dict[str, Any] = {"reverse": True}
        if limit and limit > 0:
            iter_kwargs["limit"] = limit

        async for message in self.client.iter_messages(dest, **iter_kwargs):
            if not message.text and not message.media:
                continue
            scanned += 1
            h = compute_message_hash(message)
            self._dest_hashes.add(h)
            # Yield control periodically so the event loop stays responsive
            if scanned % 100 == 0:
                await asyncio.sleep(0)

        elapsed = round(time.time() - start, 2)
        logger.info(
            f"Dest scan: {scanned} messages → {len(self._dest_hashes)} unique hashes "
            f"in {elapsed}s"
        )
        return {
            "scanned": scanned,
            "unique_hashes": len(self._dest_hashes),
            "elapsed_seconds": elapsed,
        }

    def clear_dest_cache(self) -> None:
        """Forget all destination hashes (forces re-scan next time)."""
        self._dest_hashes = set()

    # ── v1.2: Copy with selective + dedup ───────────────────

    async def copy(
        self,
        config: CopierConfig,
        progress_callback: Callable[[CopierResult, int], Any] | None = None,
    ) -> CopierResult:
        """Run the copy operation.

        v1.2 changes:
          - If ``config.selected_ids`` is set, ONLY those message IDs are sent.
          - If ``config.skip_duplicates`` is True, messages whose hash is in
            ``self._dest_hashes`` are counted as duplicates_skipped.
        """
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated — call send_code/verify_code first")

        self._cancelled = False
        result = CopierResult()
        rate = RateLimiter(base_delay=config.delay)

        # Convert selected_ids to a set for O(1) membership check
        selected_set: set[int] | None = (
            set(config.selected_ids) if config.selected_ids is not None else None
        )

        # Resume support — only when selected_ids is not set (i.e. full run)
        if selected_set is None and config.min_id is None:
            saved = self.load_progress()
            if saved.get("last_source_id", 0) > 0:
                config.min_id = saved["last_source_id"]
                logger.info(f"Resuming from message ID: {config.min_id}")

        try:
            source = await self._resolve_entity(config.source_channel)
            dest = await self._resolve_entity(config.dest_channel)
            logger.info(
                f"Copying: '{getattr(source, 'title', config.source_channel)}' → "
                f"'{getattr(dest, 'title', config.dest_channel)}'"
            )
        except Exception as e:
            raise RuntimeError(f"Cannot access channels: {e}") from e

        iter_kwargs: dict[str, Any] = {
            "reverse": config.reverse_order,
        }
        if config.limit > 0:
            iter_kwargs["limit"] = config.limit
        if config.min_id:
            iter_kwargs["min_id"] = config.min_id
        if config.max_id:
            iter_kwargs["max_id"] = config.max_id

        try:
            async for message in self.client.iter_messages(source, **iter_kwargs):
                if self._cancelled:
                    result.cancelled = True
                    break

                # v1.2: filter by selected_ids
                if selected_set is not None and message.id not in selected_set:
                    continue

                result.total += 1
                result.last_source_id = message.id

                # Filter: empty messages
                if not message.text and not message.media:
                    result.skipped += 1
                    continue

                has_media = message.media and not isinstance(
                    message.media, MessageMediaWebPage
                )
                has_text = bool(message.text and message.text.strip())

                # Filter: files_only / text_only
                if (config.files_only or not config.copy_text) and not has_media:
                    result.skipped += 1
                    continue
                if not config.copy_media and has_media and not has_text:
                    result.skipped += 1
                    continue

                # v1.2: skip duplicates
                if config.skip_duplicates and self._dest_hashes:
                    msg_hash = compute_message_hash(message)
                    if msg_hash in self._dest_hashes:
                        result.duplicates_skipped += 1
                        result.skipped += 1
                        logger.debug(
                            f"[{message.id}] skipping duplicate "
                            f"(hash={msg_hash})"
                        )
                        continue

                # Send
                ok = await self._send_one(message, dest, config, result, rate)
                if ok:
                    result.copied += 1
                    if has_media:
                        result.media_count += 1
                    if has_text:
                        result.text_count += 1
                    # v1.2: register the new hash so subsequent dups in the
                    # SAME batch are also skipped
                    if config.skip_duplicates:
                        new_hash = compute_message_hash(message)
                        self._dest_hashes.add(new_hash)
                else:
                    result.failed += 1

                # Progress callback
                if progress_callback:
                    pct = (
                        round(result.total / config.limit * 100)
                        if config.limit
                        else 0
                    )
                    try:
                        out = progress_callback(result, pct)
                        if asyncio.iscoroutine(out):
                            await out
                    except Exception:
                        pass

                # Save progress every 10 messages (only in full-run mode)
                if selected_set is None and result.total % 10 == 0:
                    self.save_progress({
                        "copied": result.copied,
                        "skipped": result.skipped,
                        "failed": result.failed,
                        "last_source_id": result.last_source_id,
                    })

                await asyncio.sleep(rate.get_delay())

        except ChatWriteForbiddenError as e:
            raise RuntimeError("No write permission in destination channel") from e
        except FloodWaitError as e:
            logger.warning(f"FloodWait {e.seconds}s — saving progress and pausing")
            self.save_progress({
                "copied": result.copied,
                "last_source_id": result.last_source_id,
            })
            await asyncio.sleep(e.seconds + 5)
        except Exception as e:
            result.errors.append(f"fatal: {e}")
            logger.error(f"Copy failed: {e}", exc_info=True)

        # Final save (only in full-run mode)
        if selected_set is None:
            self.save_progress({
                "copied": result.copied,
                "skipped": result.skipped,
                "failed": result.failed,
                "last_source_id": 0 if not result.cancelled else result.last_source_id,
            })

        logger.info(
            f"Copy done: {result.copied} ok, {result.failed} failed, "
            f"{result.skipped} skipped (of which {result.duplicates_skipped} dups), "
            f"— {result.elapsed}"
        )
        return result

    # ── Internals ───────────────────────────────────────────

    async def _send_one(
        self,
        message,
        dest,
        config: CopierConfig,
        result: CopierResult,
        rate: RateLimiter,
    ) -> bool:
        """Send one message directly via send_message(file=media)."""
        has_media = message.media and not isinstance(
            message.media, MessageMediaWebPage
        )
        try:
            if has_media and config.copy_media:
                await self.client.send_message(
                    entity=dest,
                    message=message.text or "",
                    file=message.media,
                    link_preview=False,
                    silent=True,
                )
                rate.record_success()
                return True

            if message.text and config.copy_text:
                await self.client.send_message(
                    entity=dest,
                    message=message.text,
                    link_preview=False,
                    silent=True,
                )
                rate.record_success()
                return True

            return False

        except FileReferenceError:
            logger.warning(f"[{message.id}] FileReference expired — refreshing")
            try:
                refreshed = await self.client.get_messages(message.peer_id, ids=message.id)
                if refreshed and refreshed.media:
                    await self.client.send_message(
                        entity=dest,
                        message=refreshed.text or "",
                        file=refreshed.media,
                        link_preview=False,
                        silent=True,
                    )
                    rate.record_success()
                    return True
            except Exception as e2:
                result.errors.append(f"msg#{message.id}: refresh failed: {e2}")
                return False

        except (PhotoInvalidError, DocumentInvalidError):
            result.errors.append(f"msg#{message.id}: corrupt/deleted file")
            return False

        except FloodWaitError as e:
            wait = rate.record_flood(e.seconds)
            logger.warning(
                f"[{message.id}] FloodWait {e.seconds}s — sleeping {wait:.0f}s"
            )
            await asyncio.sleep(wait)
            # Try once more after the wait
            try:
                await self.client.send_message(
                    entity=dest,
                    message=message.text or "",
                    file=message.media if has_media else None,
                    link_preview=False,
                    silent=True,
                )
                rate.record_success()
                return True
            except Exception as e3:
                result.errors.append(f"msg#{message.id}: post-flood retry failed: {e3}")
                return False

        except Exception as e:
            result.errors.append(f"msg#{message.id}: {e}")
            logger.error(f"[{message.id}] copy failed: {e}")
            return False
