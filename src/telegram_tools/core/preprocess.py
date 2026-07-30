"""
Arabic corpus preprocessor for Telegram-extracted text.

Pipeline
--------
    telegram_corpus/texts/corpus.txt
        ↓
    1. Deduplicate (exact + fuzzy SequenceMatcher)
    2. Normalize Arabic (tatweel, alef, taa marbuta, yaa, diacritics)
    3. Remove noise (URLs, mentions, hashtags, emojis, Telegram formatting)
    4. Filter by quality (min length, max repetition, Arabic ratio)
    5. Segment into sentences / paragraphs
        ↓
    processed_corpus/
      clean_corpus.txt        # normalized paragraphs
      segments.jsonl          # one segment per line, with metrics
      segments.txt            # plain text segments
      processing_stats.json   # filtering statistics
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import string
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

logger = logging.getLogger(__name__)


# ─── ArabicNormalizer ───────────────────────────────────────


class ArabicNormalizer:
    """Comprehensive Arabic text normalization."""

    ARABIC_RANGE = re.compile(
        r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]"
    )

    URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.UNICODE)
    MENTION_PATTERN = re.compile(r"@\w+", re.UNICODE)
    HASHTAG_PATTERN = re.compile(r"#\S+", re.UNICODE)
    EMOJI_PATTERN = re.compile(
        r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
        r"\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
        r"\U00002702-\U000027B0\U000024C2-\U0001F251]+",
        re.UNICODE,
    )
    TELEGRAM_FORMAT = re.compile(r"\*+|__+|`+|\[.+?\]\(.+?\)")
    EXTRA_SPACES = re.compile(r"\s+")
    EXTRA_NEWLINES = re.compile(r"\n{3,}")
    PUNCTUATION = set(string.punctuation + "،؛؟«»“”‘’…ـ")

    def normalize(self, text: str) -> str:
        """Full normalization pipeline."""
        if not text:
            return ""
        text = self._remove_tatweel(text)
        text = self._normalize_alef(text)
        text = self._normalize_taa_marbuta(text)
        text = self._normalize_yaa(text)
        text = self._remove_diacritics(text)
        text = self._remove_noise(text)
        text = self._normalize_punctuation(text)
        text = self._clean_spaces(text)
        return text.strip()

    def _remove_tatweel(self, text: str) -> str:
        return text.replace("\u0640", "")

    def _normalize_alef(self, text: str) -> str:
        return (
            text.replace("\u0625", "\u0627")
            .replace("\u0623", "\u0627")
            .replace("\u0622", "\u0627")
        )

    def _normalize_taa_marbuta(self, text: str) -> str:
        return text.replace("\u0629", "\u0647")

    def _normalize_yaa(self, text: str) -> str:
        return text.replace("\u0649", "\u064A")

    def _remove_diacritics(self, text: str) -> str:
        return "".join(
            c
            for c in text
            if not (0x064B <= ord(c) <= 0x065F or 0x0670 <= ord(c) <= 0x0670)
        )

    def _remove_noise(self, text: str) -> str:
        text = self.URL_PATTERN.sub("", text)
        text = self.MENTION_PATTERN.sub("", text)
        text = self.HASHTAG_PATTERN.sub("", text)
        text = self.EMOJI_PATTERN.sub("", text)
        text = self.TELEGRAM_FORMAT.sub("", text)
        return text

    def _normalize_punctuation(self, text: str) -> str:
        allowed = {"،", ".", "؟", "!", ":", ";", "-", "(", ")"}
        return "".join(
            c if c in allowed or c not in self.PUNCTUATION else " "
            for c in text
        )

    def _clean_spaces(self, text: str) -> str:
        text = self.EXTRA_SPACES.sub(" ", text)
        text = self.EXTRA_NEWLINES.sub("\n\n", text)
        return text.strip()


# ─── QualityFilter ──────────────────────────────────────────


class QualityFilter:
    """Filter text entries by quality metrics."""

    def __init__(
        self,
        min_chars: int = 20,
        min_words: int = 3,
        max_repetition_ratio: float = 0.4,
        min_arabic_ratio: float = 0.5,
    ):
        self.min_chars = min_chars
        self.min_words = min_words
        self.max_repetition = max_repetition_ratio
        self.min_arabic_ratio = min_arabic_ratio
        self.normalizer = ArabicNormalizer()

    def arabic_ratio(self, text: str) -> float:
        if not text:
            return 0.0
        arabic_chars = len(self.normalizer.ARABIC_RANGE.findall(text))
        total_alpha = sum(1 for c in text if c.isalpha())
        return arabic_chars / total_alpha if total_alpha > 0 else 0.0

    def repetition_ratio(self, text: str) -> float:
        if len(text) < 10:
            return 0.0
        char_counts = Counter(text)
        if not char_counts:
            return 0.0
        most_common_ratio = char_counts.most_common(1)[0][1] / len(text)
        return most_common_ratio

    def is_quality(self, text: str) -> tuple[bool, dict]:
        clean = self.normalizer.normalize(text)
        words = clean.split()
        metrics = {
            "original_length": len(text),
            "clean_length": len(clean),
            "word_count": len(words),
            "arabic_ratio": self.arabic_ratio(clean),
            "repetition_ratio": self.repetition_ratio(clean),
        }
        reasons: list[str] = []
        if len(clean) < self.min_chars:
            reasons.append("too_short")
        if len(words) < self.min_words:
            reasons.append("too_few_words")
        if metrics["arabic_ratio"] < self.min_arabic_ratio:
            reasons.append("low_arabic")
        if metrics["repetition_ratio"] > self.max_repetition:
            reasons.append("repetitive")
        metrics["pass"] = len(reasons) == 0
        metrics["fail_reasons"] = reasons
        return metrics["pass"], metrics


# ─── Deduplicator ───────────────────────────────────────────


class Deduplicator:
    """Remove exact and near-duplicate text entries."""

    def __init__(self, fuzzy_threshold: float = 0.9):
        self.fuzzy_threshold = fuzzy_threshold
        self.seen: list[str] = []

    def is_duplicate(self, text: str) -> bool:
        clean = text.strip().lower()
        if not clean:
            return True
        if clean in self.seen:
            return True
        for seen_text in self.seen:
            ratio = SequenceMatcher(None, clean, seen_text).ratio()
            if ratio >= self.fuzzy_threshold:
                return True
        self.seen.append(clean)
        return False

    def reset(self) -> None:
        self.seen.clear()


# ─── TextSegmenter ──────────────────────────────────────────


class TextSegmenter:
    """Split text into sentences / paragraphs."""

    SENTENCE_ENDERS = re.compile(r"[.؟!\n]\s*")

    def segment(self, text: str, min_segment_len: int = 15) -> list[str]:
        segments: list[str] = []
        for part in self.SENTENCE_ENDERS.split(text):
            part = part.strip()
            if len(part) >= min_segment_len:
                segments.append(part)
        if not segments and len(text.strip()) >= min_segment_len:
            segments.append(text.strip())
        return segments


# ─── CorpusProcessor ────────────────────────────────────────


class CorpusProcessor:
    """Full processing pipeline for a Telegram corpus."""

    def __init__(self, input_dir: str | Path, output_dir: str | Path):
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.normalizer = ArabicNormalizer()
        self.quality_filter = QualityFilter()
        self.deduplicator = Deduplicator()
        self.segmenter = TextSegmenter()
        self.stats: dict = {
            "total_input_entries": 0,
            "after_dedup": 0,
            "after_quality": 0,
            "total_segments": 0,
            "filtered_out": {},
        }

    def process(self) -> dict:
        """Run the full pipeline. Returns the stats dict."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        input_file = self.input_dir / "texts" / "corpus.txt"
        if not input_file.exists():
            input_file = self.input_dir / "texts" / "corpus.jsonl"
        if not input_file.exists():
            logger.error(f"No input file in {self.input_dir}/texts/")
            return self.stats

        entries = self._read_input(input_file)
        self.stats["total_input_entries"] = len(entries)
        logger.info(f"Read {len(entries)} entries from {input_file}")

        clean_texts: list[str] = []
        segments: list[dict] = []

        for i, text in enumerate(entries):
            if not text or not text.strip():
                continue

            if self.deduplicator.is_duplicate(text):
                continue
            self.stats["after_dedup"] += 1

            passed, metrics = self.quality_filter.is_quality(text)
            if not passed:
                for reason in metrics["fail_reasons"]:
                    self.stats["filtered_out"][reason] = (
                        self.stats["filtered_out"].get(reason, 0) + 1
                    )
                continue
            self.stats["after_quality"] += 1

            normalized = self.normalizer.normalize(text)
            if not normalized.strip():
                continue
            clean_texts.append(normalized)

            for seg in self.segmenter.segment(normalized):
                segments.append({
                    "text": seg,
                    "source_entry": i,
                    "char_count": len(seg),
                    "word_count": len(seg.split()),
                    "arabic_ratio": metrics["arabic_ratio"],
                })
            self.stats["total_segments"] = len(segments)

        self._save_outputs(clean_texts, segments)
        self._save_stats()

        logger.info("Processing complete!")
        logger.info(f"  Input: {self.stats['total_input_entries']}")
        logger.info(f"  After dedup: {self.stats['after_dedup']}")
        logger.info(f"  After quality: {self.stats['after_quality']}")
        logger.info(f"  Segments: {self.stats['total_segments']}")
        logger.info(f"  Filtered: {self.stats['filtered_out']}")
        return self.stats

    def _read_input(self, filepath: Path) -> list[str]:
        texts: list[str] = []
        if filepath.suffix == ".jsonl":
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        text = entry.get("text", "")
                        if text.strip():
                            texts.append(text)
                    except json.JSONDecodeError:
                        pass
        else:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            texts = [t.strip() for t in content.split("\n\n") if t.strip()]
        return texts

    def _save_outputs(self, clean_texts: list[str], segments: list[dict]) -> None:
        clean_file = self.output_dir / "clean_corpus.txt"
        with open(clean_file, "w", encoding="utf-8") as f:
            for text in clean_texts:
                f.write(text + "\n\n")

        seg_jsonl = self.output_dir / "segments.jsonl"
        with open(seg_jsonl, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(json.dumps(seg, ensure_ascii=False) + "\n")

        seg_txt = self.output_dir / "segments.txt"
        with open(seg_txt, "w", encoding="utf-8") as f:
            for seg in segments:
                f.write(seg["text"] + "\n")

    def _save_stats(self) -> None:
        stats_file = self.output_dir / "processing_stats.json"
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2, ensure_ascii=False)


# ─── CLI entry ──────────────────────────────────────────────


def _cli() -> None:
    parser = argparse.ArgumentParser(
        description="Process Telegram Arabic corpus for NLP/OCR"
    )
    parser.add_argument("--input", "-i", required=True)
    parser.add_argument("--output", "-o", default="./processed_corpus")
    parser.add_argument("--min-chars", type=int, default=20)
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--min-arabic", type=float, default=0.5)
    parser.add_argument("--fuzzy-threshold", type=float, default=0.9)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    processor = CorpusProcessor(args.input, args.output)
    processor.quality_filter.min_chars = args.min_chars
    processor.quality_filter.min_words = args.min_words
    processor.quality_filter.min_arabic_ratio = args.min_arabic
    processor.deduplicator.fuzzy_threshold = args.fuzzy_threshold
    processor.process()


if __name__ == "__main__":
    _cli()
