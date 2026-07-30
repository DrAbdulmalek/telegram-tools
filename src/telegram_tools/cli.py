#!/usr/bin/env python3
"""
Unified CLI for telegram_tools.

Subcommands
-----------
  copy      Fast bulk copy between channels (direct re-send)
  forward   Bypass 'Restrict Saving' via Download-Upload
  extract   Build a corpus from a channel's history
  process   Clean + segment an extracted Arabic corpus
  login     Interactive login + export SESSION_STRING

Environment variables
---------------------
  TG_API_ID      Telegram API ID
  TG_API_HASH    Telegram API Hash
  TG_PHONE       Phone number (for `login`)
  TG_SESSION     Optional StringSession contents (skips login)

Examples
--------
  tg-tools login --phone +963XXXXXXXXX
  tg-tools copy --source @channel --dest -1001234567890 --limit 100
  tg-tools forward --source @protected --dest -1001234567890 --delay 3
  tg-tools extract --channel @my_channel --output ./corpus --limit 500
  tg-tools process --input ./corpus --output ./processed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .core.copier import CopierConfig, TelegramCopier
from .core.extractor import TelegramExtractor
from .core.forwarder import ForwardConfig, TelegramForwarder
from .core.preprocess import CorpusProcessor
from .utils.auth import get_credentials_from_env, prompt_credentials


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _get_creds(allow_prompt: bool = True):
    creds = get_credentials_from_env()
    if creds:
        return creds
    if allow_prompt and sys.stdin.isatty():
        return prompt_credentials()
    print("ERROR: TG_API_ID and TG_API_HASH environment variables are required")
    sys.exit(2)


# ─── login ──────────────────────────────────────────────────


async def cmd_login(args: argparse.Namespace) -> int:
    creds = _get_creds()
    if args.phone:
        creds.phone = args.phone
    if not creds.phone:
        print("ERROR: phone number required (use --phone or set TG_PHONE)")
        return 2

    session_string = os.environ.get("TG_SESSION", "")
    fwd = TelegramForwarder(
        creds.api_id, creds.api_hash, session_string=session_string or None
    )
    try:
        await fwd._ensure_client()
        if await fwd.is_authorized():
            print("Already authenticated")
        else:
            await fwd.send_code(creds.phone)
            code = input("Enter the code sent to Telegram: ").strip()
            password = ""
            try:
                await fwd.verify_code(code)
            except Exception as e:
                if "2FA_PASSWORD_REQUIRED" in str(e):
                    password = input("Enter 2FA password: ").strip()
                    await fwd.verify_code(code, password)
                else:
                    raise

        ss = await fwd.export_session_string()
        print("\n=== SESSION_STRING ===")
        print(ss)
        print("=== END ===\n")
        print("Save this in HuggingFace Secrets as SESSION_STRING")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        await fwd.disconnect()


# ─── copy ───────────────────────────────────────────────────


async def cmd_copy(args: argparse.Namespace) -> int:
    creds = _get_creds()
    session_string = os.environ.get("TG_SESSION", "")
    copier = TelegramCopier(
        creds.api_id,
        creds.api_hash,
        session_string=session_string or None,
        progress_file=Path(args.progress),
    )
    try:
        await copier._ensure_client()
        if not await copier.is_authorized():
            if creds.phone:
                await copier.send_code(creds.phone)
                code = input("Code: ").strip()
                await copier.verify_code(code)
            else:
                print("ERROR: not authenticated — run `tg-tools login` first")
                return 2

        config = CopierConfig(
            source_channel=args.source,
            dest_channel=args.dest,
            limit=args.limit,
            delay=args.delay,
            copy_text=not args.files_only,
            copy_media=not args.text_only,
            files_only=args.files_only,
            reverse_order=not args.newest_first,
        )
        result = await copier.copy(config)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if not result.cancelled else 130
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        await copier.disconnect()


# ─── forward ────────────────────────────────────────────────


async def cmd_forward(args: argparse.Namespace) -> int:
    creds = _get_creds()
    session_string = os.environ.get("TG_SESSION", "")
    fwd = TelegramForwarder(
        creds.api_id,
        creds.api_hash,
        session_string=session_string or None,
    )
    try:
        await fwd._ensure_client()
        if not await fwd.is_authorized():
            if creds.phone:
                await fwd.send_code(creds.phone)
                code = input("Code: ").strip()
                await fwd.verify_code(code)
            else:
                print("ERROR: not authenticated — run `tg-tools login` first")
                return 2

        config = ForwardConfig(
            source_channel=args.source,
            dest_channel=args.dest,
            limit=args.limit,
            delay=args.delay,
            media_only=args.media_only,
            text_only=args.text_only,
            skip_forwards=not args.include_forwards,
            filter_text=args.filter,
            start_id=args.start_id or None,
            end_id=args.end_id or None,
            send_caption=not args.no_caption,
            reverse_order=args.reverse,
        )
        result = await fwd.forward_content(config)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0 if not result.cancelled else 130
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        await fwd.disconnect()


# ─── extract ────────────────────────────────────────────────


async def cmd_extract(args: argparse.Namespace) -> int:
    creds = _get_creds()
    session_string = os.environ.get("TG_SESSION", "")
    extractor = TelegramExtractor(
        creds.api_id,
        creds.api_hash,
        session_string=session_string or None,
    )
    try:
        await extractor._ensure_client()
        if not await extractor.is_authorized():
            if creds.phone:
                await extractor.send_code(creds.phone)
                code = input("Code: ").strip()
                await extractor.verify_code(code)
            else:
                print("ERROR: not authenticated — run `tg-tools login` first")
                return 2

        metadata = await extractor.extract(
            channel=args.channel,
            output_dir=args.output,
            download_media=not args.no_media,
            texts_only=args.texts_only,
            limit=args.limit,
            delay=args.delay,
            resume_from=args.resume,
        )
        print(json.dumps(metadata, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        await extractor.disconnect()


# ─── process ────────────────────────────────────────────────


def cmd_process(args: argparse.Namespace) -> int:
    processor = CorpusProcessor(args.input, args.output)
    processor.quality_filter.min_chars = args.min_chars
    processor.quality_filter.min_words = args.min_words
    processor.quality_filter.min_arabic_ratio = args.min_arabic
    processor.deduplicator.fuzzy_threshold = args.fuzzy_threshold
    stats = processor.process()
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


# ─── Argument parser ────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tg-tools",
        description="Unified Telegram toolkit (copy, forward, extract, process)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    # login
    p_login = sub.add_parser("login", help="Authenticate and export SESSION_STRING")
    p_login.add_argument("--phone", help="Phone number with country code")
    p_login.set_defaults(func=cmd_login, is_async=True)

    # copy
    p_copy = sub.add_parser("copy", help="Fast bulk copy between channels")
    p_copy.add_argument("--source", "-s", required=True, help="Source @username or ID")
    p_copy.add_argument("--dest", "-d", required=True, help="Destination ID")
    p_copy.add_argument("--limit", "-l", type=int, default=0)
    p_copy.add_argument("--delay", type=float, default=3.0)
    p_copy.add_argument("--files-only", action="store_true")
    p_copy.add_argument("--text-only", action="store_true")
    p_copy.add_argument("--newest-first", action="store_true")
    p_copy.add_argument("--progress", default="copier_progress.json")
    p_copy.set_defaults(func=cmd_copy, is_async=True)

    # forward
    p_fwd = sub.add_parser("forward", help="Bypass Restrict Saving via Download-Upload")
    p_fwd.add_argument("--source", "-s", required=True)
    p_fwd.add_argument("--dest", "-d", required=True)
    p_fwd.add_argument("--limit", "-l", type=int, default=100)
    p_fwd.add_argument("--delay", type=float, default=2.0)
    p_fwd.add_argument("--media-only", action="store_true")
    p_fwd.add_argument("--text-only", action="store_true")
    p_fwd.add_argument("--include-forwards", action="store_true")
    p_fwd.add_argument("--no-caption", action="store_true")
    p_fwd.add_argument("--reverse", action="store_true")
    p_fwd.add_argument("--filter", help="Only forward messages containing this text")
    p_fwd.add_argument("--start-id", type=int, default=0)
    p_fwd.add_argument("--end-id", type=int, default=0)
    p_fwd.set_defaults(func=cmd_forward, is_async=True)

    # extract
    p_ext = sub.add_parser("extract", help="Build a corpus from a channel")
    p_ext.add_argument("--channel", "-c", required=True)
    p_ext.add_argument("--output", "-o", default="./telegram_corpus")
    p_ext.add_argument("--no-media", action="store_true")
    p_ext.add_argument("--texts-only", "-t", action="store_true")
    p_ext.add_argument("--limit", "-l", type=int, default=0)
    p_ext.add_argument("--delay", type=float, default=2.0)
    p_ext.add_argument("--resume", "-r", type=int, default=0)
    p_ext.set_defaults(func=cmd_extract, is_async=True)

    # process
    p_proc = sub.add_parser("process", help="Clean + segment extracted corpus")
    p_proc.add_argument("--input", "-i", required=True)
    p_proc.add_argument("--output", "-o", default="./processed_corpus")
    p_proc.add_argument("--min-chars", type=int, default=20)
    p_proc.add_argument("--min-words", type=int, default=3)
    p_proc.add_argument("--min-arabic", type=float, default=0.5)
    p_proc.add_argument("--fuzzy-threshold", type=float, default=0.9)
    p_proc.set_defaults(func=cmd_process, is_async=False)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    _setup_logging(args.verbose)

    if getattr(args, "is_async", False):
        return asyncio.run(args.func(args))
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
