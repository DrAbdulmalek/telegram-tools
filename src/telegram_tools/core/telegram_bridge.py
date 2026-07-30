"""
Bridge between Telethon message fetching and the bilingual extractor.

Provides a single ``fetch_and_extract`` method that:
  1. Iterates messages from a Telegram channel via ``client.iter_messages``.
  2. Concatenates the raw texts (preserving paragraph boundaries).
  3. Passes the combined text through ``BilingualExtractor.extract_pairs``.

The raw text is returned alongside the extracted pairs so the caller can
show a preview in the UI (Batch & Preview pattern) before deciding whether
to persist the TSV.
"""

from __future__ import annotations

import logging

from telethon import TelegramClient
from telethon.sessions import StringSession

from ..pipeline.bilingual_extractor import BilingualExtractor

logger = logging.getLogger(__name__)


class TelegramBridge:
    """Fetch raw texts from a channel and extract bilingual pairs.

    Parameters
    ----------
    client : TelegramClient, optional
        An already-connected Telethon client. If ``None``, the caller
        must invoke :meth:`connect` before calling :meth:`fetch_and_extract`.
    extractor : BilingualExtractor, optional
        Defaults to a fresh ``BilingualExtractor`` instance.
    """

    def __init__(
        self,
        client: TelegramClient | None = None,
        extractor: BilingualExtractor | None = None,
    ) -> None:
        self.client = client
        self.extractor = extractor or BilingualExtractor()

    # ── Connection management ─────────────────────────────────
    def connect(
        self,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        loop=None,
    ) -> bool:
        """Create a Telethon client and connect. Returns ``is_authorized``."""
        session = StringSession(session_string) if session_string else "omni_session"
        self.client = TelegramClient(session, int(api_id), api_hash, loop=loop)
        # ``connect`` is a coroutine; callers using the bridge from sync code
        # should wrap this in their own event loop. The Gradio UI uses the
        # shared ``TelegramClientManager`` which already owns a persistent
        # loop, so we expose ``connect_async`` for that path.
        raise NotImplementedError(
            "Use connect_async() from async contexts, or pass an already-"
            "connected client via the constructor."
        )

    async def connect_async(
        self,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
        loop=None,
    ) -> bool:
        """Async version of :meth:`connect`."""
        session = StringSession(session_string) if session_string else "omni_session"
        self.client = TelegramClient(session, int(api_id), api_hash, loop=loop)
        await self.client.connect()
        return await self.client.is_user_authorized()

    # ── Fetch + extract ───────────────────────────────────────
    async def fetch_and_extract(
        self,
        channel: str,
        limit: int = 100,
        extraction_mode: str = "hybrid",
        min_text_length: int = 1,
    ) -> tuple[list[tuple[str, str]], str]:
        """
        Fetch up to ``limit`` messages from ``channel`` and extract pairs.

        Parameters
        ----------
        channel : str
            ``@username`` or numeric chat ID.
        limit : int
            Maximum number of messages to fetch (``0`` = unlimited).
        extraction_mode : str
            One of :data:`BilingualExtractor.VALID_MODES`.
        min_text_length : int
            Skip messages whose text is shorter than this.

        Returns
        -------
        (pairs, raw_text) — extracted pairs plus the concatenated raw
        text (paragraphs separated by a blank line).
        """
        if self.client is None:
            raise RuntimeError("Not connected — call connect_async() first.")

        entity = await self.client.get_entity(channel)
        raw_texts: list[str] = []
        count = 0

        async for msg in self.client.iter_messages(entity, limit=limit or None):
            if msg.text and len(msg.text.strip()) >= min_text_length:
                raw_texts.append(msg.text.strip())
                count += 1
                if count % 100 == 0:
                    logger.info("  ... fetched %d messages", count)

        logger.info("Fetched %d text messages from %s", len(raw_texts), channel)

        combined_text = "\n\n".join(raw_texts)
        pairs = self.extractor.extract_pairs(combined_text, mode=extraction_mode)

        logger.info(
            "Extracted %d pairs (mode=%s) from %d messages",
            len(pairs),
            extraction_mode,
            len(raw_texts),
        )
        return pairs, combined_text

    # ── Convenience: extract from a single string ─────────────
    def extract(self, raw_text: str, mode: str = "hybrid") -> list[tuple[str, str]]:
        """Run the extractor on an arbitrary string (no Telegram involved)."""
        return self.extractor.extract_pairs(raw_text, mode=mode)
