"""
TelegramCopier — Fast bulk copy between channels.

Strategy: re-send the original media directly via ``send_message(file=media)``.
This avoids downloading + re-uploading, so it's much faster than the
forwarder. The trade-off: it cannot bypass "Restrict Saving Content".

Use cases:
  - Public source channels
  - Private channels where you have posting rights
  - Quick mirroring / backup
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
)
from telethon.errors import (
    ChatWriteForbiddenError,
    FloodWaitError,
    PhotoInvalidError,
    DocumentInvalidError,
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


@dataclass
class CopierConfig:
    """Configuration for a copy operation."""

    source_channel: str
    dest_channel: str
    limit: int = 0  # 0 = unlimited
    delay: float = 3.0
    copy_text: bool = True
    copy_media: bool = True
    files_only: bool = False  # alias for copy_text=False
    reverse_order: bool = True  # oldest first
    min_id: Optional[int] = None  # resume support
    max_id: Optional[int] = None


@dataclass
class CopierResult:
    """Outcome of a copy operation."""

    total: int = 0
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    media_count: int = 0
    text_count: int = 0
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
            "cancelled": self.cancelled,
            "elapsed": self.elapsed,
            "last_source_id": self.last_source_id,
            "errors": self.errors[-10:],
        }


class TelegramCopier(TelegramClientMixin):
    """Fast channel-to-channel copier using direct media re-send."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "copier",
        session_string: Optional[str] = None,
        progress_file: Optional[Path] = None,
    ):
        super().__init__(api_id, api_hash, session_name, session_string)
        self.progress_file = progress_file or Path("copier_progress.json")
        self._cancelled = False

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

    async def copy(
        self,
        config: CopierConfig,
        progress_callback: Optional[Callable[[CopierResult, int], Any]] = None,
    ) -> CopierResult:
        """
        Run the copy operation.

        progress_callback is called after every message with
        (result, percent). It may be a sync or async callable.
        """
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated — call send_code/verify_code first")

        self._cancelled = False
        result = CopierResult()
        rate = RateLimiter(base_delay=config.delay)

        # Resume support
        if config.min_id is None:
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

                # Filter: files_only
                if (config.files_only or not config.copy_text) and not has_media:
                    result.skipped += 1
                    continue
                if not config.copy_media and has_media and not has_text:
                    result.skipped += 1
                    continue

                # Send
                ok = await self._send_one(message, dest, config, result, rate)
                if ok:
                    result.copied += 1
                    if has_media:
                        result.media_count += 1
                    if has_text:
                        result.text_count += 1
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

                # Save progress every 10 messages
                if result.total % 10 == 0:
                    self.save_progress({
                        "copied": result.copied,
                        "skipped": result.skipped,
                        "failed": result.failed,
                        "last_source_id": result.last_source_id,
                    })

                await asyncio.sleep(rate.get_delay())

        except ChatWriteForbiddenError:
            raise RuntimeError("No write permission in destination channel")
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

        # Final save
        self.save_progress({
            "copied": result.copied,
            "skipped": result.skipped,
            "failed": result.failed,
            "last_source_id": 0 if not result.cancelled else result.last_source_id,
        })

        logger.info(
            f"Copy done: {result.copied} ok, {result.failed} failed, "
            f"{result.skipped} skipped — {result.elapsed}"
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
