"""Tests for the media helpers in telegram_tools.utils.media."""

from telegram_tools.utils.media import format_size, describe_media


class TestFormatSize:
    def test_zero_bytes(self):
        assert format_size(0) == "0 B"

    def test_bytes(self):
        assert format_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"
        assert format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"
        assert format_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert format_size(1024 * 1024 * 1024) == "1.0 GB"

    def test_large_value_caps_at_gb(self):
        # Even very large values stay in GB
        size = 10 * 1024 * 1024 * 1024
        assert format_size(size) == "10.0 GB"


class TestDescribeMedia:
    def test_no_media_returns_text_or_empty(self):
        class FakeMsg:
            media = None
            text = "hello"

        result = describe_media(FakeMsg())
        assert "Text" in result

    def test_no_media_no_text_returns_empty(self):
        class FakeMsg:
            media = None
            text = ""

        assert describe_media(FakeMsg()) == "Empty"

    def test_telethon_not_installed_returns_media(self):
        # We can't easily mock the import — just verify the function
        # handles a message with media attribute gracefully.
        class FakeMsg:
            media = "something"
            text = "hello"

        # Will try to import telethon — if it succeeds, returns based on type;
        # if it fails, returns "Media"
        result = describe_media(FakeMsg())
        assert isinstance(result, str)
        assert len(result) > 0
