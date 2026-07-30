"""
Tests for ``TelegramClientManager`` singleton and ``TelegramBridge``
extraction logic.

The Telethon client itself is not exercised here (no network); we only
verify the singleton mechanics, loop initialization, and the bridge's
``extract`` shortcut which delegates to ``BilingualExtractor``.
"""

from __future__ import annotations

import pytest

from telegram_tools.core.client_manager import TelegramClientManager
from telegram_tools.core.telegram_bridge import TelegramBridge
from telegram_tools.pipeline.bilingual_extractor import BilingualExtractor


class TestTelegramClientManagerSingleton:
    def setup_method(self):
        TelegramClientManager._reset_singleton()

    def teardown_method(self):
        TelegramClientManager._reset_singleton()

    def test_construction_returns_same_instance(self):
        a = TelegramClientManager()
        b = TelegramClientManager()
        assert a is b

    def test_reset_singleton_creates_new_instance(self):
        a = TelegramClientManager()
        TelegramClientManager._reset_singleton()
        b = TelegramClientManager()
        assert a is not b

    def test_loop_is_initialized(self):
        mgr = TelegramClientManager()
        assert mgr._loop is not None
        assert not mgr._loop.is_closed()
        assert mgr._loop_thread is not None
        assert mgr._loop_thread.is_alive()

    def test_is_authorized_returns_false_when_no_client(self):
        mgr = TelegramClientManager()
        assert mgr.is_authorized() is False

    def test_export_session_raises_when_not_connected(self):
        mgr = TelegramClientManager()
        with pytest.raises(RuntimeError, match="Not connected"):
            mgr.export_session_string()


class TestTelegramBridgeExtract:
    """The ``extract`` method is a thin shortcut to BilingualExtractor."""

    def setup_method(self):
        self.bridge = TelegramBridge(client=None, extractor=BilingualExtractor())

    def test_extract_returns_pairs(self):
        text = "Heart - قلب\nBone - عظم"
        pairs = self.bridge.extract(text, mode="hybrid")
        assert len(pairs) >= 2
        ens = {en.lower() for en, _ in pairs}
        assert "heart" in ens
        assert "bone" in ens

    def test_extract_passes_mode_through(self):
        text = "Chronic Obstructive Pulmonary Disease\nمرض الانسداد الرئوي المزمن"
        # structured mode should NOT pick up the sequential pair.
        structured = self.bridge.extract(text, mode="structured")
        sequential = self.bridge.extract(text, mode="sequential")
        assert len(sequential) >= 1
        # Structured might still produce 0 pairs (or 1 if it falls through).
        # The important guarantee: sequential >= structured for this input.
        assert len(sequential) >= len(structured)

    def test_extract_with_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            self.bridge.extract("Heart - قلب", mode="bogus")

    def test_fetch_and_extract_raises_when_not_connected(self):
        import asyncio
        bridge = TelegramBridge(client=None)
        with pytest.raises(RuntimeError, match="Not connected"):
            asyncio.new_event_loop().run_until_complete(
                bridge.fetch_and_extract("@x", limit=1)
            )
