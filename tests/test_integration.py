"""Integration tests for the CLI argument parser and auth helpers."""

import os
from unittest.mock import patch

import pytest

from telegram_tools.cli import build_parser
from telegram_tools.utils.auth import Credentials, get_credentials_from_env, prompt_credentials


class TestCLIParser:
    def test_login_subcommand(self):
        parser = build_parser()
        args = parser.parse_args(["login", "--phone", "+963999999999"])
        assert args.command == "login"
        assert args.phone == "+963999999999"
        assert args.is_async is True

    def test_copy_subcommand(self):
        parser = build_parser()
        args = parser.parse_args([
            "copy", "--source", "@chan", "--dest", "-100123",
            "--limit", "50", "--delay", "5",
        ])
        assert args.command == "copy"
        assert args.source == "@chan"
        assert args.dest == "-100123"
        assert args.limit == 50
        assert args.delay == 5.0

    def test_forward_subcommand(self):
        parser = build_parser()
        args = parser.parse_args([
            "forward", "-s", "@src", "-d", "@dst",
            "--media-only", "--reverse",
        ])
        assert args.command == "forward"
        assert args.source == "@src"
        assert args.dest == "@dst"
        assert args.media_only is True
        assert args.reverse is True

    def test_extract_subcommand(self):
        parser = build_parser()
        args = parser.parse_args([
            "extract", "--channel", "@my_channel", "--texts-only",
            "--limit", "100",
        ])
        assert args.command == "extract"
        assert args.channel == "@my_channel"
        assert args.texts_only is True
        assert args.limit == 100

    def test_process_subcommand(self):
        parser = build_parser()
        args = parser.parse_args([
            "process", "--input", "./corpus", "--output", "./out",
            "--min-chars", "30", "--min-arabic", "0.6",
        ])
        assert args.command == "process"
        assert args.input == "./corpus"
        assert args.output == "./out"
        assert args.min_chars == 30
        assert args.min_arabic == 0.6
        assert args.is_async is False

    def test_no_subcommand_fails(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["-v", "login", "--phone", "+123"])
        assert args.verbose is True


class TestGetCredentialsFromEnv:
    def test_returns_none_when_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_credentials_from_env() is None

    def test_returns_credentials_when_set(self):
        with patch.dict(
            os.environ,
            {"TG_API_ID": "12345", "TG_API_HASH": "abcdef1234567890"},
            clear=True,
        ):
            creds = get_credentials_from_env()
            assert creds is not None
            assert creds.api_id == 12345
            assert creds.api_hash == "abcdef1234567890"

    def test_invalid_api_id_returns_none(self):
        with patch.dict(
            os.environ,
            {"TG_API_ID": "not_a_number", "TG_API_HASH": "abcdef1234567890"},
            clear=True,
        ):
            assert get_credentials_from_env() is None

    def test_phone_optional(self):
        with patch.dict(
            os.environ,
            {"TG_API_ID": "12345", "TG_API_HASH": "abcdef1234567890"},
            clear=True,
        ):
            creds = get_credentials_from_env()
            assert creds.phone is None

    def test_phone_set(self):
        with patch.dict(
            os.environ,
            {
                "TG_API_ID": "12345",
                "TG_API_HASH": "abcdef1234567890",
                "TG_PHONE": "+963999999999",
            },
            clear=True,
        ):
            creds = get_credentials_from_env()
            assert creds.phone == "+963999999999"


class TestCredentialsDataclass:
    def test_creation(self):
        c = Credentials(api_id=123, api_hash="hash", phone="+123")
        assert c.api_id == 123
        assert c.api_hash == "hash"
        assert c.phone == "+123"

    def test_phone_default_none(self):
        c = Credentials(api_id=123, api_hash="hash")
        assert c.phone is None
