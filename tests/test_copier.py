"""
Tests for CopierConfig, CopierResult, and TelegramCopier data structures.
Live Telegram operations are not unit-tested.
"""

import pytest

from telegram_tools.core.copier import CopierConfig, CopierResult


class TestCopierConfig:
    def test_default_values(self):
        config = CopierConfig(source_channel="src", dest_channel="dst")
        assert config.source_channel == "src"
        assert config.dest_channel == "dst"
        assert config.limit == 0
        assert config.delay == 3.0
        assert config.copy_text is True
        assert config.copy_media is True
        assert config.files_only is False
        assert config.reverse_order is True
        assert config.min_id is None
        assert config.max_id is None

    def test_custom_values(self):
        config = CopierConfig(
            source_channel="@chan",
            dest_channel="-100123",
            limit=500,
            delay=5.0,
            copy_text=False,
            copy_media=False,
            files_only=True,
            reverse_order=False,
            min_id=100,
            max_id=200,
        )
        assert config.limit == 500
        assert config.delay == 5.0
        assert config.copy_text is False
        assert config.copy_media is False
        assert config.files_only is True
        assert config.reverse_order is False
        assert config.min_id == 100
        assert config.max_id == 200


class TestCopierResult:
    def test_default_values(self):
        r = CopierResult()
        assert r.total == 0
        assert r.copied == 0
        assert r.skipped == 0
        assert r.failed == 0
        assert r.media_count == 0
        assert r.text_count == 0
        assert r.cancelled is False
        assert r.errors == []
        assert r.last_source_id == 0

    def test_to_dict(self):
        r = CopierResult(
            total=20, copied=15, skipped=3, failed=2,
            media_count=10, text_count=5,
        )
        d = r.to_dict()
        assert d["total"] == 20
        assert d["copied"] == 15
        assert d["skipped"] == 3
        assert d["failed"] == 2
        assert d["media"] == 10
        assert d["text"] == 5
        assert d["cancelled"] is False
        assert "elapsed" in d
        assert "last_source_id" in d
        assert "errors" in d

    def test_elapsed_format(self):
        r = CopierResult()
        # elapsed is computed from start_time
        assert "elapsed" in r.to_dict()
        # Format: HH:MM:SS
        elapsed = r.elapsed
        assert len(elapsed) == 8
        assert elapsed[2] == ":"
        assert elapsed[5] == ":"

    def test_errors_truncated_in_dict(self):
        r = CopierResult()
        r.errors = [f"err_{i}" for i in range(15)]
        d = r.to_dict()
        assert len(d["errors"]) == 10
        assert d["errors"][-1] == "err_14"
