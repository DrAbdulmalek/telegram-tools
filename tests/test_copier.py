"""
Tests for CopierConfig, CopierResult, TelegramCopier data structures,
and v1.2 preview/dedup helpers.
Live Telegram operations are not unit-tested.
"""


from telegram_tools.core.copier import (
    CopierConfig,
    CopierResult,
    CopyPreview,
    _normalize_text,
    compute_message_hash,
)


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


# ═══════════════════════════════════════════════════════════
#  v1.2: Preview, dedup, select-all tests
# ═══════════════════════════════════════════════════════════


class TestCopierConfigV12:
    """Tests for the new v1.2 fields on CopierConfig."""

    def test_v12_defaults(self):
        config = CopierConfig(source_channel="src", dest_channel="dst")
        assert config.skip_duplicates is False
        assert config.selected_ids is None

    def test_v12_skip_duplicates(self):
        config = CopierConfig(
            source_channel="src", dest_channel="dst",
            skip_duplicates=True,
        )
        assert config.skip_duplicates is True

    def test_v12_selected_ids(self):
        config = CopierConfig(
            source_channel="src", dest_channel="dst",
            selected_ids=[10, 20, 30],
        )
        assert config.selected_ids == [10, 20, 30]


class TestCopierResultV12:
    """Tests for the new v1.2 fields on CopierResult."""

    def test_duplicates_skipped_default(self):
        r = CopierResult()
        assert r.duplicates_skipped == 0

    def test_to_dict_includes_duplicates_skipped(self):
        r = CopierResult(duplicates_skipped=5)
        d = r.to_dict()
        assert d["duplicates_skipped"] == 5


class TestNormalizeText:
    """Tests for the text normalization helper used by the hash function."""

    def test_lowercases(self):
        assert _normalize_text("HELLO") == "hello"

    def test_collapses_whitespace(self):
        assert _normalize_text("hello   world") == "hello world"

    def test_collapses_newlines(self):
        assert _normalize_text("hello\n\nworld") == "hello world"

    def test_strips_outer_whitespace(self):
        assert _normalize_text("  hello  ") == "hello"

    def test_empty(self):
        assert _normalize_text("") == ""
        assert _normalize_text(None) == ""


class TestComputeMessageHash:
    """Tests for the deterministic SHA-256 hashing of message content."""

    def _make_fake_text_message(self, text):
        """Build a minimal fake Telethon message with only a .text attribute."""
        class FakeMsg:
            def __init__(self, text):
                self.text = text
                self.media = None
        return FakeMsg(text)

    def test_text_messages_with_same_text_have_same_hash(self):
        m1 = self._make_fake_text_message("Hello World")
        m2 = self._make_fake_text_message("Hello World")
        assert compute_message_hash(m1) == compute_message_hash(m2)

    def test_text_messages_with_different_text_have_different_hash(self):
        m1 = self._make_fake_text_message("Hello World")
        m2 = self._make_fake_text_message("Hello World 2")
        assert compute_message_hash(m1) != compute_message_hash(m2)

    def test_whitespace_only_differences_produce_same_hash(self):
        """Normalized text means 'a  b' and 'a b' hash to the same value."""
        m1 = self._make_fake_text_message("hello   world")
        m2 = self._make_fake_text_message("hello world")
        assert compute_message_hash(m1) == compute_message_hash(m2)

    def test_case_differences_produce_same_hash(self):
        """Normalized text lowercases — 'HELLO' and 'hello' hash the same."""
        m1 = self._make_fake_text_message("HELLO WORLD")
        m2 = self._make_fake_text_message("hello world")
        assert compute_message_hash(m1) == compute_message_hash(m2)

    def test_hash_is_hex_string_of_fixed_length(self):
        m = self._make_fake_text_message("test")
        h = compute_message_hash(m)
        assert isinstance(h, str)
        assert len(h) == 16
        # All chars must be hex
        assert all(c in "0123456789abcdef" for c in h)


class TestCopyPreview:
    """Tests for the CopyPreview dataclass."""

    def test_default_values(self):
        p = CopyPreview(
            message_id=1,
            date="2026-01-01",
            text_snippet="hello",
            has_media=False,
            media_type="none",
        )
        assert p.dup_status == "unknown"
        assert p.selected is True
        assert p.media_size_mb == 0.0
        assert p.media_name == ""
        assert p.content_hash == ""

    def test_to_dict(self):
        p = CopyPreview(
            message_id=42,
            date="2026-01-01",
            text_snippet="hello",
            has_media=True,
            media_type="photo",
            media_size_mb=1.5,
            media_name="photo.jpg",
            content_hash="abc123",
            dup_status="duplicate",
        )
        d = p.to_dict()
        assert d["message_id"] == 42
        assert d["media_type"] == "photo"
        assert d["dup_status"] == "duplicate"
        assert d["selected"] is True  # default
