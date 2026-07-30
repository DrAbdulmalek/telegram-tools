"""
TelegramExtractor + CorpusSaver — Build NLP/OCR-ready corpora.

Extracts texts and downloads media from a Telegram channel into an
organized directory structure suitable for downstream NLP/OCR pipelines
(e.g. the Arabic preprocessor or BilingualExtractor).

Output structure
----------------
    output_dir/
      texts/
        corpus.txt       # plain text, paragraphs separated by blank lines
        corpus.jsonl     # one JSON entry per text message
      media/
        images/          # .jpg .png .gif .webp
        videos/          # .mp4 .avi .mkv
        audio/           # .mp3 .ogg
        documents/       # .pdf .docx .xlsx .pptx
        other/
      metadata.json      # extraction summary
      summary.txt        # human-readable summary
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from telethon import TelegramClient, errors
from telethon.tl.types import (
    MessageMediaDocument,
    MessageMediaPhoto,
    MessageMediaWebPage,
)

from .base import TelegramClientMixin

logger = logging.getLogger(__name__)


# ─── Media helpers ──────────────────────────────────────────


def get_media_extension(document) -> str:
    """Return the file extension for a Telethon Document."""
    mime = document.mime_type or ""
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "video/avi": ".avi",
        "video/mkv": ".mkv",
        "audio/mp3": ".mp3",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "application/pdf": ".pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
        "application/msword": ".doc",
        "application/vnd.ms-excel": ".xls",
        "application/vnd.ms-powerpoint": ".ppt",
        "text/plain": ".txt",
        "text/csv": ".csv",
    }
    return ext_map.get(mime, ".bin")


def get_media_category(document) -> str:
    """Categorize a Document for the output folder structure."""
    mime = document.mime_type or ""
    name = ""
    if document.attributes:
        first = document.attributes[0]
        if hasattr(first, "file_name") and first.file_name:
            name = first.file_name
    name_lower = name.lower()

    if "image" in mime or mime in (
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    ):
        return "images"
    if "video" in mime:
        return "videos"
    if "audio" in mime:
        return "audio"
    if "pdf" in name_lower or "pdf" in mime:
        return "documents"
    if any(
        ext in name_lower
        for ext in [".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"]
    ):
        return "documents"
    return "other"


# ─── CorpusSaver ────────────────────────────────────────────


class CorpusSaver:
    """Writes extracted texts and media metadata to disk."""

    def __init__(self, output_dir: str | Path):
        self.output = Path(output_dir)
        self.output.mkdir(parents=True, exist_ok=True)
        self.texts_dir = self.output / "texts"
        self.media_dir = self.output / "media"
        self.texts_dir.mkdir(exist_ok=True)
        self.media_dir.mkdir(exist_ok=True)
        self.all_texts: list[dict] = []
        self.metadata: dict = {
            "extracted_at": datetime.now().isoformat(),
            "total_messages": 0,
            "text_messages": 0,
            "media_files": 0,
            "categories": {},
            "errors": [],
        }

    def save_text(self, msg_id: int, text: str, date, has_media: bool = False) -> None:
        entry = {
            "msg_id": msg_id,
            "text": text,
            "date": date.isoformat() if hasattr(date, "isoformat") else str(date),
            "has_media": has_media,
            "char_count": len(text),
            "word_count": len(text.split()),
        }
        self.all_texts.append(entry)
        self.metadata["text_messages"] += 1

    def record_media(
        self, msg_id: int, filename: str, category: str, size_mb: float, mime: str
    ) -> None:
        cat = self.metadata["categories"]
        cat[category] = cat.get(category, 0) + 1
        self.metadata["media_files"] += 1

    def save_corpus(self) -> None:
        # JSONL — one entry per line
        texts_file = self.texts_dir / "corpus.jsonl"
        with open(texts_file, "w", encoding="utf-8") as f:
            for entry in self.all_texts:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # Plain text — paragraphs separated by blank lines
        plain_file = self.texts_dir / "corpus.txt"
        with open(plain_file, "w", encoding="utf-8") as f:
            for entry in self.all_texts:
                if entry["text"].strip():
                    f.write(entry["text"].strip() + "\n\n")

        # Metadata
        meta_file = self.output / "metadata.json"
        with open(meta_file, "w", encoding="utf-8") as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)

        # Human-readable summary
        summary_file = self.output / "summary.txt"
        with open(summary_file, "w", encoding="utf-8") as f:
            f.write("Telegram Corpus Extraction Summary\n")
            f.write("=" * 50 + "\n")
            f.write(f"Extracted at: {self.metadata['extracted_at']}\n")
            f.write(
                f"Total messages processed: {self.metadata['total_messages']}\n"
            )
            f.write(f"Text entries: {self.metadata['text_messages']}\n")
            f.write(f"Media files: {self.metadata['media_files']}\n")
            f.write("\nCategories:\n")
            for cat, count in self.metadata["categories"].items():
                f.write(f"  {cat}: {count}\n")
            f.write("\nOutput files:\n")
            f.write("  texts/corpus.txt   - Plain text\n")
            f.write("  texts/corpus.jsonl - JSON lines with metadata\n")
            f.write("  metadata.json      - Full extraction metadata\n")


# ─── Extractor ──────────────────────────────────────────────


class TelegramExtractor(TelegramClientMixin):
    """Extract texts and media from a Telegram channel."""

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_name: str = "extractor",
        session_string: Optional[str] = None,
    ):
        super().__init__(api_id, api_hash, session_name, session_string)
        self.saver: Optional[CorpusSaver] = None

    async def extract(
        self,
        channel: str,
        output_dir: str | Path,
        download_media: bool = True,
        texts_only: bool = False,
        limit: int = 0,
        delay: float = 2.0,
        resume_from: int = 0,
    ) -> dict:
        """Run the extraction. Returns the metadata dict."""
        if not self.client:
            await self._ensure_client()
        if not await self.is_authorized():
            raise RuntimeError("Not authenticated")

        self.saver = CorpusSaver(output_dir)

        entity = await self._resolve_entity(channel)
        title = getattr(entity, "title", str(channel))
        logger.info(f"Extracting from: {title}")

        count = 0
        media_count = 0
        last_id = 0

        try:
            async for message in self.client.iter_messages(entity, reverse=True):
                if limit > 0 and count >= limit:
                    break
                if message.id <= resume_from:
                    continue

                last_id = message.id
                has_media = message.media is not None
                has_text = bool(message.text and message.text.strip())

                if has_text:
                    self.saver.save_text(
                        msg_id=message.id,
                        text=message.text.strip(),
                        date=message.date,
                        has_media=has_media,
                    )

                if has_media and download_media and not texts_only:
                    ok = await self._download_one(message)
                    if ok:
                        media_count += 1

                count += 1
                self.saver.metadata["total_messages"] = count

                if count % 50 == 0:
                    logger.info(
                        f"Progress: {count} msgs | "
                        f"texts: {self.saver.metadata['text_messages']} | "
                        f"media: {media_count}"
                    )

                await asyncio.sleep(delay)

        except errors.FloodWaitError as e:
            logger.warning(f"FloodWait: {e.seconds}s — saving progress")
            self.saver.save_corpus()
            logger.info(f"Resume with --resume {last_id}")
        except KeyboardInterrupt:
            logger.info("Interrupted — saving progress")
        except Exception as e:
            logger.error(f"Extraction error: {e}")
            self.saver.metadata["errors"].append(str(e))

        self.saver.save_corpus()
        logger.info(
            f"Done: texts={self.saver.metadata['text_messages']}, "
            f"media={media_count}, output={output_dir}"
        )
        return self.saver.metadata

    async def _download_one(self, message) -> bool:
        """Download a single media message. Returns True on success."""
        if not self.saver:
            return False
        try:
            category = "unknown"
            ext = ".bin"
            size_mb = 0.0
            mime = ""

            if isinstance(message.media, MessageMediaPhoto):
                category = "images"
                ext = ".jpg"
            elif isinstance(
                message.media, MessageMediaDocument
            ) and message.media.document:
                doc = message.media.document
                category = get_media_category(doc)
                ext = get_media_extension(doc)
                size_mb = doc.size / (1024 * 1024) if doc.size else 0
                mime = doc.mime_type or ""

            cat_dir = self.saver.media_dir / category
            cat_dir.mkdir(exist_ok=True)
            filename = (
                f"{message.id:06d}_"
                f"{message.date.strftime('%Y%m%d_%H%M%S')}{ext}"
            )
            filepath = cat_dir / filename
            if not filepath.exists():
                await self.client.download_media(message, file=str(filepath))

            self.saver.record_media(
                msg_id=message.id,
                filename=f"{category}/{filename}",
                category=category,
                size_mb=size_mb,
                mime=mime,
            )
            return True

        except (errors.PhotoInvalidError, errors.DocumentInvalidError):
            logger.warning(f"  [{message.id}] Media corrupt/deleted")
            return False
        except Exception as e:
            logger.warning(f"  [{message.id}] Download failed: {e}")
            return False


# ─── CLI entry ──────────────────────────────────────────────


async def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Extract texts and media from a Telegram channel"
    )
    parser.add_argument("--channel", "-c", required=True, help="Channel @username or ID")
    parser.add_argument("--output", "-o", default="./telegram_corpus")
    parser.add_argument("--texts-only", "-t", action="store_true")
    parser.add_argument("--no-media", action="store_true")
    parser.add_argument("--limit", "-l", type=int, default=0)
    parser.add_argument("--delay", "-d", type=float, default=2.0)
    parser.add_argument("--resume", "-r", type=int, default=0)
    args = parser.parse_args()

    api_id = os.environ.get("TG_API_ID", "")
    api_hash = os.environ.get("TG_API_HASH", "")
    if not api_id or not api_hash:
        print("Set TG_API_ID and TG_API_HASH environment variables")
        sys.exit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    extractor = TelegramExtractor(int(api_id), api_hash)
    try:
        await extractor._ensure_client()
        if not await extractor.is_authorized():
            await extractor.client.start()  # interactive login
        await extractor.extract(
            channel=args.channel,
            output_dir=args.output,
            download_media=not args.no_media,
            texts_only=args.texts_only,
            limit=args.limit,
            delay=args.delay,
            resume_from=args.resume,
        )
    finally:
        await extractor.disconnect()


if __name__ == "__main__":
    asyncio.run(_cli())
