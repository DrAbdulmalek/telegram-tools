#!/usr/bin/env python3
"""
Headless sync pipeline — fetch from Telegram, extract pairs, split, and
optionally upload to HuggingFace Hub. Designed for ``cron`` / GitHub Actions.

Usage
-----
    # Local run (fetch 500 msgs, extract, split, save TSVs locally)
    python -m automation.headless_sync \\
        --channel @dr_zaky_ortho --limit 500 --mode hybrid

    # Full automation (fetch, extract, split, upload to HF Hub)
    python -m automation.headless_sync \\
        --channel @dr_zaky_ortho --limit 1000 \\
        --upload --repo-name medical-glossary-weekly --private

    # Using environment variables (recommended for cron)
    export TG_API_ID=12345
    export TG_API_HASH='your_hash'
    export TG_SESSION_STRING='1BVtsOK...'
    export HF_TOKEN='hf_...'
    python -m automation.headless_sync --channel @dr_zaky_ortho --upload \\
        --repo-name my-dataset

Exit codes
----------
    0 — success
    1 — argument / credential error
    2 — Telegram connection / authorization failure
    3 — pipeline execution failure
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Make the package importable when running the script directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from telethon.sessions import StringSession

from src.telegram_tools.pipeline.bilingual_extractor import BilingualExtractor
from src.telegram_tools.pipeline.splitter import DatasetSplitter
from src.telegram_tools.pipeline.hf_uploader import HuggingFaceUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("headless_sync")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Omni Telegram Suite — Headless Sync",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Telegram credentials (fall back to env vars).
    p.add_argument("--api-id", type=int, default=os.environ.get("TG_API_ID"),
                   help="Telegram API ID (or TG_API_ID env var)")
    p.add_argument("--api-hash", type=str, default=os.environ.get("TG_API_HASH"),
                   help="Telegram API Hash (or TG_API_HASH env var)")
    p.add_argument("--session", type=str, default=os.environ.get("TG_SESSION_STRING"),
                   help="Telethon StringSession (or TG_SESSION_STRING env var)")

    # Source.
    p.add_argument("--channel", type=str, required=True,
                   help="Target channel (@username or -100... id)")
    p.add_argument("--limit", type=int, default=100,
                   help="Max messages to fetch (0 = all)")

    # Extraction.
    p.add_argument("--mode", type=str, default="hybrid",
                   choices=["hybrid", "structured", "sequential", "contextual"],
                   help="Extraction algorithm")

    # Output.
    p.add_argument("--output-dir", type=str,
                   default=str(Path.home() / "omni_telegram_output"),
                   help="Local output directory")
    p.add_argument("--train-ratio", type=float, default=0.8,
                   help="Training set ratio (0-1)")
    p.add_argument("--val-ratio", type=float, default=0.1,
                   help="Validation set ratio (0-1)")
    p.add_argument("--format", type=str, default="tsv",
                   choices=["tsv", "jsonl"],
                   help="Output file format")

    # HuggingFace upload.
    p.add_argument("--upload", action="store_true",
                   help="Upload splits to HuggingFace Hub")
    p.add_argument("--hf-token", type=str, default=os.environ.get("HF_TOKEN"),
                   help="HuggingFace token (or HF_TOKEN env var)")
    p.add_argument("--repo-name", type=str,
                   help="HF dataset repo name (without username)")
    p.add_argument("--public", action="store_true",
                   help="Make HF repo public (default: private)")

    return p.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if not args.api_id or not args.api_hash:
        logger.error("API_ID and API_HASH are required (flag or env var).")
        sys.exit(1)
    if args.upload and (not args.hf_token or not args.repo_name):
        logger.error("--hf-token and --repo-name are required when --upload is set.")
        sys.exit(1)
    if args.train_ratio + args.val_ratio >= 1.0:
        logger.error("train_ratio + val_ratio must be < 1.0")
        sys.exit(1)


async def fetch_raw_texts(client: TelegramClient, channel: str, limit: int) -> list[str]:
    logger.info("Fetching up to %d messages from '%s'...", limit, channel)
    entity = await client.get_entity(channel)
    texts: list[str] = []
    async for msg in client.iter_messages(entity, limit=limit or None):
        if msg.text and msg.text.strip():
            texts.append(msg.text.strip())
    logger.info("Fetched %d text messages.", len(texts))
    return texts


async def run_pipeline(args: argparse.Namespace) -> None:
    # 1. Connect to Telegram.
    logger.info("Connecting to Telegram...")
    session = StringSession(args.session) if args.session else "headless_session"
    client = TelegramClient(session, args.api_id, args.api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        if not args.session:
            logger.warning("No active session — interactive login required.")
            phone = input("Phone number (with country code, e.g. +963...): ").strip()
            await client.send_code_request(phone)
            code = input("Verification code: ").strip()
            try:
                await client.sign_in(phone, code)
            except Exception:
                pwd = input("2FA password: ").strip()
                await client.sign_in(password=pwd)
            # Persist the new session string for next time.
            new_str = client.session.save()
            logger.info("Session string (save for next run): %s", new_str[:60] + "...")
        else:
            logger.error("Session string is invalid or expired.")
            sys.exit(2)

    me = await client.get_me()
    logger.info("Connected as: %s (id=%s)", me.first_name, me.id)

    try:
        # 2. Fetch texts.
        raw_texts = await fetch_raw_texts(client, args.channel, args.limit)
        if not raw_texts:
            logger.warning("No texts found in channel. Exiting.")
            return
        combined_text = "\n\n".join(raw_texts)

        # 3. Extract pairs.
        logger.info("Extracting pairs (mode=%s)...", args.mode)
        extractor = BilingualExtractor()
        pairs = extractor.extract_pairs(combined_text, mode=args.mode)
        logger.info("Extracted %d unique pairs.", len(pairs))
        if not pairs:
            logger.warning("No pairs extracted. Check channel content or mode.")
            return

        # 4. Save raw corpus + aligned TSV (Dual Save).
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        splits_dir = out_dir / "ml_splits"
        splits_dir.mkdir(exist_ok=True)

        raw_path = out_dir / "raw_corpus.txt"
        raw_path.write_text(combined_text, encoding="utf-8")
        logger.info("Saved raw corpus → %s", raw_path)

        glossary_path = out_dir / "bilingual_glossary.tsv"
        count = extractor.save_to_tsv(pairs, glossary_path)
        logger.info("Saved %d pairs → %s", count, glossary_path)

        # 5. Split (with shuffle to break alphabetical bias).
        logger.info(
            "Splitting (train=%.2f, val=%.2f, test=%.2f)...",
            args.train_ratio, args.val_ratio, 1.0 - args.train_ratio - args.val_ratio,
        )
        splitter = DatasetSplitter(seed=42)
        splits = splitter.split_data(pairs, args.train_ratio, args.val_ratio)
        saved = splitter.save_splits(splits, splits_dir, file_format=args.format)
        logger.info("\n%s", splitter.summary(splits))
        for name, path in saved.items():
            logger.info("  %s: %s", name, path)

        # 6. Optional HF upload.
        if args.upload:
            logger.info("Uploading to HuggingFace Hub (%s)...",
                        "public" if args.public else "private")
            try:
                uploader = HuggingFaceUploader(token=args.hf_token)
                url = uploader.upload_dataset(
                    folder_path=splits_dir,
                    repo_name=args.repo_name,
                    private=not args.public,
                )
                logger.info("Upload complete: %s", url)
            except Exception as exc:
                logger.error("Upload failed: %s", exc)

        logger.info("Pipeline completed successfully.")
    finally:
        await client.disconnect()


def main() -> None:
    args = parse_args()
    validate_args(args)

    try:
        asyncio.run(run_pipeline(args))
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("Critical error: %s", exc, exc_info=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
