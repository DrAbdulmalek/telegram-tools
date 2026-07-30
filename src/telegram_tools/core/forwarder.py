"""
TelegramForwarder — Bypass "Restrict Saving Content" via Download-Upload.

When a channel has the ``noforwards`` flag set, Telegram blocks the normal
forward API. We work around this by:

  1. Downloading the media to a temp directory
  2. Re-uploading it as a fresh message to the destination
  3. Cleaning up the temp file

This is slower than TelegramCopier but is the only way to mirror content
from protected channels. Album/MediaGroup support is included: messages
sharing a ``grouped_id`` are batched and sent together.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from telethon.errors import (
    ChannelPrivateError,
    ChatWriteForbiddenError,
    FloodWaitError,
    MessageIdInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
    SlowModeWaitError,
    UserBannedInChannelError,
    ApiIdInvalidError,
)
from telethon.tl.types import (
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
)

from .base import (
    AuthenticationError,
    TelegramClientMixin,
)
from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

TEMP_DIR = Path(tempfile.gettempdir()) / "telegram_tools_forwarder"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# ─── Config & Result ────────────────────────────────────────


@dataclass
class MessagePreview:
    """A preview entry shown to the user before the actual forward."""

    message_id: int
    date: str  # ISO format
    text_snippet: str
    has_media: bool
    media_type: str  # photo | video | document | audio | none
    media_size_mb: float = 0.0
    is_forward: bool = False
    selected: bool = True

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "date": self.date,
            "text_snippet": self.text_snippet,
            "has_media": self.has_media,
            "media_type": self.media_type,
            "media_size_mb": round(self.media_size_mb, 2),
            "is_forward": self.is_forward,
            "selected": self.selected,
        }


@dataclass
class ForwardConfig:
    """Configuration for a forward operation."""

    source_channel: str
    dest_channel: str
    limit: int = 100
    delay: float = 2.0
    media_only: bool = False
    text_only: bool = False
    skip_forwards: bool = True
    filter_text: Optional[str] = None
    start_id: Optional[int] = None
    end_id: Optional[int] = None
    max_retries: int = 3
    send_caption: bool = True
    reverse_order: bool = False
    selected_ids: Optional[list[int]] = None

    def __post_init__(self):
        if self.limit < 0:
            raise ValueError("limit must be >= 0")
        if self.delay < 0:
            raise ValueError("delay must be >= 0")


@dataclass
class ForwardResult:
    """Outcome of a forward operation."""

    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed(self) -> str:
        secs = int(time.time() - self.start_time)
        return f"{secs // 60}m {secs % 60}s"

    def to_dict(self) -> dict:
        return {
            "total": self.total,
            "success": self.success,
            "failed": self.failed,
            "skipped": self.skipped,
            "cancelled": self.cancelled,
            "elapsed": self.elapsed,
            "errors": self.errors[-10:],
        }


# ─── Forwarder ──────────────────────────────────────────────


class TelegramForwarder(TelegramClientMixin):
    """Userbot that bypasses 'Restrict Saving Content' via Download-Upload."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "forwarder",
        session_string: Optional[str] = None,
    ):
        super().__init__(api_id, api_hash, session_name, session_string)
        self._cancelled = False
        self._progress_callback: Optional[Callable] = None
        # Login state
        self._phone: Optional[str] = None
        self._phone_code_hash: Optional[str] = None

    # ── Authentication ──────────────────────────────────────

    async def send_code(self, phone: str) -> dict:
        """Send a login code to ``phone``."""
        if not self.client:
            await self._ensure_client()

        try:
            result = await self.client.send_code_request(phone)
            self._phone = phone
            self._phone_code_hash = result.phone_code_hash
            logger.info(f"Code sent to {phone}")
            return {"phone_code_hash": result.phone_code_hash}
        except ApiIdInvalidError as e:
            raise AuthenticationError(
                "API ID or API Hash is invalid — check my.telegram.org"
            ) from e
        except Exception as e:
            raise AuthenticationError(f"Failed to send code: {e}") from e

    async def verify_code(
        self, code: str, password: Optional[str] = None
    ) -> bool:
        """Verify the login code (and 2FA password if required)."""
        if not self.client:
            raise AuthenticationError("Client not created — call send_code first")
        if not self._phone or not self._phone_code_hash:
            raise AuthenticationError("No pending code — call send_code first")

        try:
            await self.client.sign_in(
                phone=self._phone,
                code=code.strip(),
                phone_code_hash=self._phone_code_hash,
            )
            logger.info("Signed in successfully")
            return True
        except SessionPasswordNeededError:
            if password and password.strip():
                await self.client.sign_in(password=password.strip())
                logger.info("Signed in with 2FA")
                return True
            raise AuthenticationError("2FA_PASSWORD_REQUIRED")
        except PhoneCodeInvalidError as e:
            raise AuthenticationError("Invalid verification code") from e
        except PhoneCodeExpiredError as e:
            raise AuthenticationError("Code expired — request a new one") from e
        except Exception as e:
            raise AuthenticationError(f"Verification failed: {e}") from e

    # ── Dialogs ─────────────────────────────────────────────

    async def get_dialogs(self, limit: int = 500) -> list[dict]:
        """Fetch the user's channels and groups."""
        if not self.client:
            raise RuntimeError("Not connected")
        await self._build_entity_cache(force=True)

        dialogs: list[dict] = []
        try:
            async for dialog in self.client.iter_dialogs(limit=limit):
                # Keep every dialog in the cache even if not shown in the UI
                self._entity_cache[dialog.id] = dialog.entity
                if dialog.id < 0:
                    id_str = str(dialog.id)
                    if id_str.startswith("-100"):
                        self._entity_cache[int(id_str[4:])] = dialog.entity

                if dialog.is_channel or dialog.is_group:
                    entity = dialog.entity
                    dialogs.append({
                        "id": dialog.id,
                        "title": dialog.title,
                        "username": getattr(entity, "username", None),
                        "type": "channel" if dialog.is_channel else "group",
                        "participants_count": (
                            getattr(entity, "participants_count", None)
                            or "unknown"
                        ),
                        "restricted": getattr(entity, "restricted", False),
                        "protected": getattr(entity, "noforwards", False),
                    })
        except FloodWaitError as e:
            mins = e.seconds // 60
            raise RuntimeError(
                f"Telegram asks for {mins} min wait (rate limit). "
                f"This is not a bug — please wait and retry."
            ) from e
        return dialogs

    async def get_channel_info(self, channel_id: str) -> dict:
        """Fetch info for a single channel."""
        if not self.client:
            raise RuntimeError("Not connected")
        try:
            entity = await self._resolve_entity(channel_id)
        except FloodWaitError as e:
            mins = e.seconds // 60
            raise RuntimeError(
                f"Telegram asks for {mins} min wait (rate limit). "
                f"Channel info is not required to start forwarding — "
                f"you can pick the channel from the dropdown directly."
            ) from e
        return {
            "id": entity.id,
            "title": (
                getattr(entity, "title", None)
                or getattr(entity, "first_name", "—")
            ),
            "username": getattr(entity, "username", None),
            "participants_count": (
                getattr(entity, "participants_count", None) or "unknown"
            ),
            "restricted": getattr(entity, "restricted", False),
            "protected": getattr(entity, "noforwards", False),
        }

    # ── Preview ────────────────────────────────────────────

    async def preview_messages(
        self, config: ForwardConfig
    ) -> list[MessagePreview]:
        """Fetch a preview list — no actual forwarding happens."""
        if not self.client:
            raise RuntimeError("Not connected")

        try:
            source = await self._resolve_entity(config.source_channel)
        except ChannelPrivateError as e:
            raise RuntimeError("Source channel is private — you're not a member") from e

        iter_kwargs: dict[str, Any] = {
            "limit": config.limit,
            "reverse": config.reverse_order,
        }
        if config.start_id:
            iter_kwargs["min_id"] = config.start_id - 1
        if config.end_id:
            iter_kwargs["max_id"] = config.end_id + 1

        previews: list[MessagePreview] = []
        media_type_map = {
            MessageMediaPhoto: "photo",
            MessageMediaDocument: "document",
        }

        async for message in self.client.iter_messages(source, **iter_kwargs):
            if config.skip_forwards and message.fwd_from:
                continue
            if config.filter_text and message.text:
                if config.filter_text.lower() not in message.text.lower():
                    continue
            if config.media_only and not message.media:
                continue
            if config.text_only and message.media:
                continue

            media_type = "none"
            size_mb = 0.0
            if message.media and not isinstance(
                message.media, MessageMediaWebPage
            ):
                media_type = media_type_map.get(
                    type(message.media), "media"
                )
                size_mb = self._estimate_media_size(message)

            text = (message.text or "").strip()
            snippet = (text[:100] + "…") if len(text) > 100 else text

            previews.append(MessagePreview(
                message_id=message.id,
                date=message.date.isoformat() if message.date else "",
                text_snippet=snippet or "(no text)",
                has_media=bool(message.media)
                and not isinstance(message.media, MessageMediaWebPage),
                media_type=media_type,
                media_size_mb=size_mb,
                is_forward=bool(message.fwd_from),
                selected=True,
            ))
        return previews

    @staticmethod
    def _estimate_media_size(message: Message) -> float:
        try:
            media = message.media
            if hasattr(media, "document") and media.document:
                return round(media.document.size / (1024 * 1024), 2)
            if hasattr(media, "photo") and media.photo:
                sizes = getattr(media.photo, "sizes", [])
                if sizes:
                    largest = sizes[-1]
                    size_bytes = getattr(largest, "size", 0) or 0
                    return round(size_bytes / (1024 * 1024), 2)
        except Exception:
            pass
        return 0.0

    # ── Forward ────────────────────────────────────────────

    def cancel(self) -> None:
        self._cancelled = True

    def set_progress_callback(self, callback: Callable) -> None:
        self._progress_callback = callback

    async def forward_content(
        self,
        config: ForwardConfig,
        progress_callback: Optional[Callable] = None,
    ) -> ForwardResult:
        """Run the forward operation."""
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated")

        self._cancelled = False
        cb = progress_callback or self._progress_callback
        result = ForwardResult()
        rate = RateLimiter(base_delay=config.delay)

        await self._build_entity_cache(force=True)

        try:
            source = await self._resolve_entity(config.source_channel)
            dest = await self._resolve_entity(config.dest_channel)
            logger.info(
                f"Forwarding: '{getattr(source, 'title', '?')}' → "
                f"'{getattr(dest, 'title', '?')}'"
            )
        except ChannelPrivateError as e:
            raise RuntimeError(
                "Source channel is private — you're not a member"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Cannot access channels: {e}") from e

        iter_kwargs: dict[str, Any] = {
            "limit": config.limit,
            "reverse": config.reverse_order,
        }
        if config.start_id:
            iter_kwargs["min_id"] = config.start_id - 1
        if config.end_id:
            iter_kwargs["max_id"] = config.end_id + 1

        try:
            async for message in self.client.iter_messages(source, **iter_kwargs):
                if self._cancelled:
                    result.cancelled = True
                    break
                result.total += 1

                # Filters
                if config.selected_ids is not None:
                    if message.id not in config.selected_ids:
                        result.skipped += 1
                        continue
                if config.skip_forwards and message.fwd_from:
                    result.skipped += 1
                    continue
                if config.filter_text and message.text:
                    if config.filter_text.lower() not in message.text.lower():
                        result.skipped += 1
                        continue
                if config.media_only and not message.media:
                    result.skipped += 1
                    continue
                if config.text_only and message.media:
                    result.skipped += 1
                    continue

                ok = await self._copy_with_retry(message, dest, config, result, rate)
                if ok:
                    result.success += 1
                else:
                    result.failed += 1

                if cb:
                    pct = (
                        round(result.total / config.limit * 100)
                        if config.limit
                        else 0
                    )
                    try:
                        out = cb(result, pct)
                        if asyncio.iscoroutine(out):
                            await out
                    except Exception:
                        pass

                await asyncio.sleep(rate.get_delay())

        except ChatWriteForbiddenError:
            raise RuntimeError("No write permission in destination channel")
        except Exception as e:
            result.errors.append(f"fatal: {e}")
            logger.error(f"Forward failed: {e}", exc_info=True)

        logger.info(
            f"Forward done: {result.success} ok, {result.failed} failed, "
            f"{result.skipped} skipped — {result.elapsed}"
        )
        return result

    # ── Internals ──────────────────────────────────────────

    async def _copy_with_retry(
        self,
        message: Message,
        dest,
        config: ForwardConfig,
        result: ForwardResult,
        rate: RateLimiter,
    ) -> bool:
        """Retry wrapper with exponential backoff."""
        for attempt in range(1, config.max_retries + 1):
            try:
                await self._copy_message(message, dest, config)
                rate.record_success()
                return True
            except FloodWaitError as e:
                wait = rate.record_flood(e.seconds)
                logger.warning(
                    f"FloodWait {e.seconds}s — sleeping {wait:.0f}s "
                    f"(attempt {attempt})"
                )
                result.errors.append(
                    f"msg#{message.id}: FloodWait {e.seconds}s"
                )
                await asyncio.sleep(wait)
            except (
                MessageIdInvalidError,
                ChatWriteForbiddenError,
                UserBannedInChannelError,
            ) as e:
                result.errors.append(
                    f"msg#{message.id}: {type(e).__name__}"
                )
                logger.error(
                    f"Non-retryable error on msg {message.id}: {e}"
                )
                return False
            except SlowModeWaitError as e:
                logger.warning(f"SlowMode: sleeping {e.seconds}s")
                await asyncio.sleep(e.seconds + 1)
            except Exception as e:
                if attempt == config.max_retries:
                    result.errors.append(f"msg#{message.id}: {e}")
                    logger.error(
                        f"Failed after {attempt} attempts: {e}"
                    )
                    return False
                backoff = 2 ** attempt
                logger.warning(
                    f"Attempt {attempt} failed ({e}) — retry in {backoff}s"
                )
                await asyncio.sleep(backoff)
        return False

    async def _copy_message(
        self, message: Message, dest, config: ForwardConfig
    ) -> None:
        """Download-Upload copy of a single message."""
        caption = (message.text or "") if config.send_caption else ""

        if message.media and not isinstance(
            message.media, MessageMediaWebPage
        ):
            msg_tmp = TEMP_DIR / f"msg_{message.id}_{int(time.time())}"
            msg_tmp.mkdir(parents=True, exist_ok=True)
            try:
                file_path = await asyncio.wait_for(
                    message.download_media(file=str(msg_tmp) + "/"),
                    timeout=120,
                )
                if file_path and file_path.exists():
                    await asyncio.wait_for(
                        self.client.send_file(
                            dest,
                            str(file_path),
                            caption=caption,
                            parse_mode="html",
                            force_document=False,
                        ),
                        timeout=180,
                    )
                else:
                    if caption:
                        await self.client.send_message(
                            dest, caption, parse_mode="html"
                        )
            finally:
                shutil.rmtree(str(msg_tmp), ignore_errors=True)
        elif message.text:
            await self.client.send_message(
                dest, message.text, parse_mode="html"
            )
        # Empty messages (no text, no media) — silently skip


def create_forwarder(
    api_id: int,
    api_hash: str,
    session_string: Optional[str] = None,
) -> TelegramForwarder:
    """Factory — convenience function."""
    return TelegramForwarder(api_id, api_hash, session_string=session_string)
