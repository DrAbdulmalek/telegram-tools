"""
Singleton Telegram client manager with a persistent asyncio event loop.

Problem
-------
Telethon's ``TelegramClient`` is bound to the event loop it was created on.
Gradio runs callbacks in a thread pool, and each callback may end up on a
different thread — so a client created in one callback throws
``RuntimeError: ... got Future <Future pending> attached to a different loop``
when used from another.

Solution
--------
This module spins up **one** background thread running one
``asyncio.run_forever`` loop. Every coroutine is submitted to that loop via
``asyncio.run_coroutine_threadsafe``. The client lives for the lifetime of
the process and is shared across all Gradio callbacks.

This pattern is borrowed from the original ``telegram-forwarder`` project
and is the same one already used by ``src/telegram_tools/core/base.py``
(``TelegramClientMixin``). The difference is that ``TelegramClientManager``
is a true singleton — constructing it twice returns the same instance.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession

logger = logging.getLogger(__name__)


class TelegramClientManager:
    """Singleton owning a persistent asyncio loop and a single Telethon client."""

    _instance: Optional["TelegramClientManager"] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    _loop_thread: Optional[threading.Thread] = None

    def __new__(cls) -> "TelegramClientManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init_loop()
        return cls._instance

    # Singleton reset — useful for tests.
    @classmethod
    def _reset_singleton(cls) -> None:
        if cls._instance is not None and cls._loop is not None:
            try:
                cls._loop.call_soon_threadsafe(cls._loop.stop)
            except Exception:  # pragma: no cover
                pass
        cls._instance = None
        cls._loop = None
        cls._loop_thread = None

    def _init_loop(self) -> None:
        """Spin up the background asyncio loop exactly once."""
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._loop.run_forever,
            name="telegram-client-loop",
            daemon=True,
        )
        self._loop_thread.start()
        self.client: Optional[TelegramClient] = None
        logger.debug("Persistent event loop started on background thread")

    def _run(self, coro, timeout: float = 120.0):
        """Submit ``coro`` to the persistent loop and block on the result."""
        if self._loop is None:
            raise RuntimeError("Event loop not initialized")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Public API ────────────────────────────────────────────
    def create_client(
        self,
        api_id: int,
        api_hash: str,
        session_string: Optional[str] = None,
    ) -> TelegramClient:
        """
        Create (or replace) the shared Telethon client.

        Parameters
        ----------
        api_id, api_hash : str / int
            Telegram API credentials from https://my.telegram.org.
        session_string : str, optional
            A previously-exported ``StringSession``. When provided, the
            client is immediately authorized without re-sending an SMS
            code. When omitted, a file-backed session named ``omni_session``
            is used (requires interactive login on first run).
        """
        if self.client is not None:
            try:
                self._run(self.client.disconnect())
            except Exception:  # pragma: no cover
                logger.warning("Failed to disconnect previous client", exc_info=True)

        session = StringSession(session_string) if session_string else "omni_session"
        self.client = TelegramClient(
            session,
            int(api_id),
            api_hash.strip(),
            loop=self._loop,
        )
        self._run(self.client.connect())
        logger.info("TelegramClient created (session=%s)", "string" if session_string else "file")
        return self.client

    def is_authorized(self) -> bool:
        if self.client is None:
            return False
        try:
            return bool(self._run(self.client.is_user_authorized()))
        except Exception:  # pragma: no cover
            logger.warning("is_user_authorized() failed", exc_info=True)
            return False

    def export_session_string(self) -> str:
        """Return the current session as a string (save it in HF Secrets)."""
        if self.client is None or not self.is_authorized():
            raise RuntimeError("Not connected or not authorized")
        return self.client.session.save()

    def disconnect(self) -> None:
        if self.client is not None:
            try:
                self._run(self.client.disconnect())
            finally:
                self.client = None
