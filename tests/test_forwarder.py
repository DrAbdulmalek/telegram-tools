"""
Tests for ForwardConfig, ForwardResult, MessagePreview, and RateLimiter.
The TelegramForwarder class itself requires a live Telegram connection
and is not unit-tested here — only its data structures and helpers.
"""

import pytest

from telegram_tools.core.forwarder import (
    ForwardConfig,
    ForwardResult,
    MessagePreview,
)
from telegram_tools.core.rate_limiter import RateLimiter


# ─── ForwardConfig ─────────────────────────────────────────


class TestForwardConfig:
    def test_default_values(self):
        config = ForwardConfig(source_channel="src", dest_channel="dst")
        assert config.source_channel == "src"
        assert config.dest_channel == "dst"
        assert config.limit == 100
        assert config.delay == 2.0
        assert config.media_only is False
        assert config.text_only is False
        assert config.skip_forwards is True
        assert config.send_caption is True
        assert config.reverse_order is False
        assert config.max_retries == 3
        assert config.selected_ids is None

    def test_custom_values(self):
        config = ForwardConfig(
            source_channel="src",
            dest_channel="dst",
            limit=50,
            delay=5.0,
            media_only=True,
            text_only=False,
            skip_forwards=False,
            filter_text="test",
            start_id=10,
            end_id=20,
            send_caption=False,
            reverse_order=True,
            max_retries=5,
            selected_ids=[1, 2, 3],
        )
        assert config.source_channel == "src"
        assert config.dest_channel == "dst"
        assert config.limit == 50
        assert config.delay == 5.0
        assert config.media_only is True
        assert config.text_only is False
        assert config.skip_forwards is False
        assert config.filter_text == "test"
        assert config.start_id == 10
        assert config.end_id == 20
        assert config.send_caption is False
        assert config.reverse_order is True
        assert config.max_retries == 5
        assert config.selected_ids == [1, 2, 3]

    def test_negative_limit_raises(self):
        with pytest.raises(ValueError):
            ForwardConfig(source_channel="src", dest_channel="dst", limit=-10)

    def test_negative_delay_raises(self):
        with pytest.raises(ValueError):
            ForwardConfig(source_channel="src", dest_channel="dst", delay=-1.0)

    def test_zero_limit_allowed(self):
        config = ForwardConfig(source_channel="src", dest_channel="dst", limit=0)
        assert config.limit == 0

    def test_zero_delay_allowed(self):
        config = ForwardConfig(source_channel="src", dest_channel="dst", delay=0.0)
        assert config.delay == 0.0


# ─── ForwardResult ─────────────────────────────────────────


class TestForwardResult:
    def test_default_values(self):
        r = ForwardResult()
        assert r.total == 0
        assert r.success == 0
        assert r.failed == 0
        assert r.skipped == 0
        assert r.cancelled is False
        assert r.errors == []
        assert "elapsed" in r.to_dict()

    def test_to_dict(self):
        r = ForwardResult(
            total=15,
            success=10,
            failed=2,
            skipped=3,
        )
        d = r.to_dict()
        assert isinstance(d, dict)
        assert d["total"] == 15
        assert d["success"] == 10
        assert d["failed"] == 2
        assert d["skipped"] == 3
        assert d["cancelled"] is False
        assert "elapsed" in d
        assert "errors" in d

    def test_errors_truncated_in_dict(self):
        r = ForwardResult()
        r.errors = [f"error_{i}" for i in range(20)]
        d = r.to_dict()
        assert len(d["errors"]) == 10  # only last 10
        assert d["errors"][-1] == "error_19"


# ─── MessagePreview ────────────────────────────────────────


class TestMessagePreview:
    def test_to_dict(self):
        p = MessagePreview(
            message_id=42,
            date="2026-01-01T12:00:00",
            text_snippet="نص تجريبي",
            has_media=True,
            media_type="photo",
            media_size_mb=1.5,
            is_forward=False,
        )
        d = p.to_dict()
        assert d["message_id"] == 42
        assert d["date"] == "2026-01-01T12:00:00"
        assert d["text_snippet"] == "نص تجريبي"
        assert d["has_media"] is True
        assert d["media_type"] == "photo"
        assert d["media_size_mb"] == 1.5
        assert d["is_forward"] is False
        assert d["selected"] is True  # default

    def test_default_selected(self):
        p = MessagePreview(
            message_id=1, date="", text_snippet="", has_media=False, media_type="none"
        )
        assert p.selected is True


# ─── RateLimiter ───────────────────────────────────────────


class TestRateLimiter:
    def test_initial_delay_is_base(self):
        rl = RateLimiter(base_delay=2.0)
        assert rl.get_delay() == 2.0

    def test_record_flood_doubles_delay(self):
        rl = RateLimiter(base_delay=2.0)
        rl.record_flood(5)
        assert rl.get_delay() == 4.0  # 2 * 2^1

    def test_record_flood_twice_quadruples(self):
        rl = RateLimiter(base_delay=2.0)
        rl.record_flood(5)
        rl.record_flood(5)
        assert rl.get_delay() == 8.0  # 2 * 2^2

    def test_record_flood_returns_max(self):
        rl = RateLimiter(base_delay=2.0)
        # Telegram asks for 30s, our backoff would be 4s — should return 30
        wait = rl.record_flood(30)
        assert wait == 30.0

    def test_record_flood_returns_backoff_if_higher(self):
        rl = RateLimiter(base_delay=2.0)
        rl.record_flood(1)  # bump flood_count to 1, backoff = 4s
        # Telegram asks for 1s, our backoff is 4s — should return 4
        # NOTE: record_flood also increments flood_count, so after this call
        # flood_count = 2, backoff = 8s, but the return value should still
        # be max(1, 8) = 8
        wait = rl.record_flood(1)
        assert wait == 8.0  # 2 * 2^2 = 8 after the second flood

    def test_delay_capped_at_max(self):
        rl = RateLimiter(base_delay=2.0)
        for _ in range(10):
            rl.record_flood(1)
        assert rl.get_delay() == RateLimiter.MAX_DELAY  # 60s

    def test_success_relaxes_after_streak(self):
        rl = RateLimiter(base_delay=2.0)
        rl.record_flood(5)  # delay becomes 4s
        for _ in range(RateLimiter.RELAX_AFTER_SUCCESSES):
            rl.record_success()
        # flood_count should have decreased by 1
        assert rl.get_delay() == 2.0  # back to base

    def test_reset(self):
        rl = RateLimiter(base_delay=2.0)
        rl.record_flood(5)
        rl.record_success()
        rl.reset()
        assert rl._flood_count == 0
        assert rl._success_streak == 0
        assert rl.get_delay() == 2.0

    def test_state_snapshot(self):
        rl = RateLimiter(base_delay=3.0)
        rl.record_flood(5)
        s = rl.state
        assert s["base_delay"] == 3.0
        assert s["current_delay"] == 6.0
        assert s["flood_count"] == 1
        assert s["success_streak"] == 0

    def test_negative_base_delay_raises(self):
        with pytest.raises(ValueError):
            RateLimiter(base_delay=-1.0)
