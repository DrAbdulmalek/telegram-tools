"""
Base classes, exceptions, and shared mixin for telegram_tools.

Design notes
------------
All Telethon-using operations share three concerns:

1. Persistent event loop
   Telethon's TelegramClient binds itself to the running asyncio loop at
   connect() time and refuses to be used from a different loop afterwards.
   We expose a single shared loop (created lazily on demand) and route
   every coroutine through `TelegramClientMixin._run(coro)`.

2. Session management
   Two session strategies are supported:
     - file session    : persisted as <session_name>.session on disk
     - StringSession   : in-memory, exportable as a string for HF Secrets

3. Entity resolution cache
   Telethon requires an `access_hash` for every channel/chat — and the
   only reliable way to obtain it is via `iter_dialogs()`. We build a
   {id: entity} cache lazily and refresh it on demand.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from telethon import TelegramClient
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)


# ─── Exceptions ──────────────────────────────────────────────


class TelegramToolsError(Exception):
    """Base exception for all telegram_tools errors."""


class AuthenticationError(TelegramToolsError):
    """Raised when login / verification fails."""


class ChannelAccessError(TelegramToolsError):
    """Raised when a channel cannot be accessed (private, banned, etc)."""


class FloodWaitRetryableError(TelegramToolsError):
    """Raised when Telegram demands a wait — caller should retry."""

    def __init__(self, wait_seconds: int, message: str = ""):
        self.wait_seconds = wait_seconds
        super().__init__(message or f"FloodWait: {wait_seconds}s")


# ─── Shared Persistent Event Loop ────────────────────────────
# A single background thread runs one asyncio loop forever. Every
# Telethon client created by any module runs on this same loop.

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()
_shutdown_event = threading.Event()


def _shutdown_shared_loop() -> None:
    """Gracefully stop the shared loop (registered via atexit)."""
    global _loop, _loop_thread
    _shutdown_event.set()
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_loop.stop)
    if _loop_thread is not None and _loop_thread.is_alive():
        _loop_thread.join(timeout=5.0)


def _get_shared_loop() -> asyncio.AbstractEventLoop:
    """Return the shared persistent event loop, creating it on first call."""
    global _loop, _loop_thread

    if _loop is not None and not _loop.is_closed():
        return _loop

    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()

            # Register clean shutdown at interpreter exit
            import atexit
            atexit.register(_shutdown_shared_loop)

            def _runner() -> None:
                asyncio.set_event_loop(_loop)
                while not _shutdown_event.is_set():
                    _loop.run_forever()
                # Drain any pending coroutines before exiting
                pending = asyncio.all_tasks(_loop)
                if pending:
                    _loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )

            _loop_thread = threading.Thread(
                target=_runner, name="telegram-tools-loop", daemon=False
            )
            _loop_thread.start()

    return _loop


# ─── Mixin ───────────────────────────────────────────────────


class TelegramClientMixin:
    """
    Shared utility for any class that needs a TelegramClient.

    Subclasses must call ``self._ensure_client()`` before any Telethon
    operation. The mixin guarantees the client is created on the shared
    loop, connected, and (optionally) authorized.

    Attributes
    ----------
    api_id : int
    api_hash : str
    session_name : str
        Filesystem session name (used when session_string is None).
    session_string : Optional[str]
        StringSession contents — preferred for HF Spaces and Docker.
    client : Optional[TelegramClient]
        Lazily created. None until _ensure_client() is called.
    """

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "telegram_tools",
        session_string: str | None = None,
    ):
        if not api_id or not api_hash:
            raise ValueError("api_id and api_hash are required")

        self.api_id = int(api_id)
        self.api_hash = str(api_hash).strip()
        self.session_name = session_name
        self.session_string = session_string

        self.client: TelegramClient | None = None
        self._loop = _get_shared_loop()
        # {id: entity} cache built from iter_dialogs — required so that
        # numeric channel IDs can be resolved with a valid access_hash.
        self._entity_cache: dict[int, Any] = {}

    # ── Loop bridge ──────────────────────────────────────────

    def _run(self, coro, timeout: float = 120.0) -> Any:
        """Schedule coro on the shared loop and block until it returns."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Client lifecycle ─────────────────────────────────────

    async def _ensure_client(self) -> TelegramClient:
        """Create + connect the TelegramClient if not already done.

        If a previous client exists but is disconnected, reconnect it
        instead of creating a new one (preserves the auth_key on disk).
        """
        if self.client and self.client.is_connected():
            return self.client

        # Re-use the existing (disconnected) client — just reconnect it
        if self.client and not self.client.is_connected():
            try:
                await self.client.connect()
                return self.client
            except Exception as e:
                logger.warning(f"Reconnect failed, will rebuild: {e}")
                self.client = None

        if self.session_string:
            session: Any = StringSession(self.session_string)
        else:
            session = self.session_name

        self.client = TelegramClient(
            session,
            self.api_id,
            self.api_hash,
            loop=self._loop,
            catch_up=False,
            sequential_updates=True,
        )
        await self.client.connect()
        return self.client

    async def is_authorized(self) -> bool:
        """True if the client is connected and logged in.

        v1.2.1 fix: lazily creates + connects the client when called, so
        that any tool (copier, extractor) sharing the same session_string
        as the forwarder will automatically be authenticated after a
        successful forwarder login. Previously, ``is_authorized()``
        returned False whenever ``self.client`` was None — which was the
        case for the copier/extractor because only ``send_code()``
        triggered ``_ensure_client()`` on the forwarder.

        This also fixes the Session-String login flow: when the user
        pastes a valid StringSession, ``is_authorized()`` now builds the
        client and checks auth, so the UI can skip the phone/code step
        entirely.
        """
        if not self.client or not self.client.is_connected():
            try:
                await self._ensure_client()
            except Exception as e:
                logger.debug(f"_ensure_client failed in is_authorized: {e}")
                return False
        if not self.client:
            return False
        try:
            return await self.client.is_user_authorized()
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None
        self._entity_cache.clear()
        logger.info("Disconnected")

    # ── Session export ───────────────────────────────────────

    async def export_session_string(self) -> str:
        """
        Export the current session as a StringSession string.

        Works for any session type (SQLiteSession or StringSession). We
        rebuild a fresh StringSession from the underlying auth_key + dc
        info because SQLiteSession.save() returns None (it persists to
        disk automatically).
        """
        if not self.client:
            raise RuntimeError("Not connected")

        if isinstance(self.client.session, StringSession):
            saved = self.client.session.save()
            if saved:
                return saved

        session = self.client.session
        auth_key = getattr(session, "auth_key", None)
        # Telethon >=2.0 wraps auth_key in a Key object
        if hasattr(auth_key, "key"):
            auth_key = auth_key.key
        if auth_key is None or not isinstance(auth_key, bytes):
            raise RuntimeError(
                "Cannot export session — auth_key is missing. "
                "Complete authentication first."
            )

        new_ss = StringSession()
        new_ss.set_dc(
            session.dc_id,
            session.server_address,
            session.port,
        )
        new_ss.auth_key = auth_key
        exported = new_ss.save()
        if not exported:
            raise RuntimeError("Failed to build session string")
        return exported

    # ─── Entity resolution ────────────────────────────────────

    async def _build_entity_cache(self, force: bool = False) -> None:
        """
        Build a {id: entity} cache from iter_dialogs().

        Required because Telegram API demands a valid access_hash for
        every channel/chat, and the only reliable source is the dialog
        list. Manual construction via PeerChannel(id) fails with
        "Cannot find any entity" even when the ID is correct.

        force=True rebuilds even if the cache already exists.
        """
        if not force and self._entity_cache:
            return
        if not self.client:
            return

        self._entity_cache.clear()
        try:
            async for dialog in self.client.iter_dialogs():
                self._entity_cache[dialog.id] = dialog.entity
                # Also index by the positive form (without -100 prefix)
                # so callers passing either form get a hit.
                if dialog.id < 0:
                    id_str = str(dialog.id)
                    if id_str.startswith("-100"):
                        self._entity_cache[int(id_str[4:])] = dialog.entity
        except Exception as e:
            logger.warning(f"Entity cache build failed: {e}")

    @staticmethod
    def _is_numeric_id(s: str) -> bool:
        s = s.strip()
        if s.startswith("-"):
            s = s[1:]
        return s.isdigit()

    async def _resolve_entity(self, identifier):
        """
        Resolve a channel identifier to a Telethon entity.

        Accepts:
          - @username
          - https://t.me/username or https://t.me/+invite links
          - Numeric ID: 1234567890 or -1001234567890
        """
        if not self.client:
            raise RuntimeError("Not connected")

        identifier = str(identifier).strip()

        # t.me links
        if "t.me/" in identifier:
            cleaned = identifier.split("t.me/")[-1].lstrip("@")
            try:
                return await self.client.get_entity(cleaned)
            except Exception:
                pass

        # @username or non-numeric
        if identifier.startswith("@") or not self._is_numeric_id(identifier):
            return await self.client.get_entity(identifier)

        # Numeric ID — rely on the entity cache (has access_hash)
        raw_id = int(identifier)
        await self._build_entity_cache()

        if raw_id in self._entity_cache:
            return self._entity_cache[raw_id]

        # Try the alternate form (-100xxx ↔ xxx)
        if raw_id < 0:
            id_str = str(raw_id)
            if id_str.startswith("-100"):
                positive_id = int(id_str[4:])
                if positive_id in self._entity_cache:
                    return self._entity_cache[positive_id]
        else:
            negative_id = int(f"-100{raw_id}")
            if negative_id in self._entity_cache:
                return self._entity_cache[negative_id]

        # Last resort — will fail without access_hash, but try anyway
        try:
            return await self.client.get_entity(raw_id)
        except Exception as e:
            raise ChannelAccessError(
                f"Channel '{identifier}' not found. "
                f"Make sure you are a member, or pick it from the dropdown "
                f"list (which guarantees a valid access_hash)."
            ) from e
