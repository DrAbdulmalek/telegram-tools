"""
Hybrid bilingual extractor — pulls (English, Arabic) pairs from raw Telegram
corpora while preserving the original medical text verbatim (zero
normalization of diacritics, ta-marbuta, alef variants, etc.).

Three extraction strategies
---------------------------
1. **structured**  — pairs appear on the same line, separated by ``-`` ``:``
   ``|`` or wrapped in parentheses: ``Heart - قلب`` / ``قلب (Heart)``.
2. **sequential**  — pairs appear on adjacent lines (EN line directly above
   AR line, or vice-versa).
3. **contextual**  — pairs are embedded in free-flowing text; we pick the
   longest Latin run and longest Arabic run in the same paragraph.

The ``hybrid`` mode (default) applies all three in order of confidence:
structured > sequential > contextual. Each paragraph is matched by exactly
one strategy to avoid double-counting.

Output contract
---------------
``save_to_tsv`` writes a strict ``English\\tArabic`` TSV with a single
header row. Internal newlines and tabs inside a field are replaced with
spaces (structural cleaning only) — the medical content itself is never
altered.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


# Compiled once at import time.
_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")
_LATIN_RANGE = re.compile(r"[A-Za-z][A-Za-z\s\-\.]+")

# Same-line patterns. Named groups make the matching order-independent:
# we accept ``en - ar`` and ``ar - en`` alike.
_SAME_LINE_PATTERNS: tuple[re.Pattern, ...] = (
    # English - Arabic   |   English : Arabic   |   English | Arabic
    re.compile(
        r"(?P<en>[A-Za-z][A-Za-z\s\-\.]+?)\s*[-|:]\s*"
        r"(?P<ar>[\u0600-\u06FF][\u0600-\u06FF\s\.]+)"
    ),
    # Arabic - English
    re.compile(
        r"(?P<ar>[\u0600-\u06FF][\u0600-\u06FF\s\.]+?)\s*[-|:]\s*"
        r"(?P<en>[A-Za-z][A-Za-z\s\-\.]+)"
    ),
    # English (Arabic)
    re.compile(
        r"(?P<en>[A-Za-z][A-Za-z\s\-\.]+?)\s*\(\s*"
        r"(?P<ar>[\u0600-\u06FF][\u0600-\u06FF\s\.]+?)\s*\)"
    ),
    # Arabic (English)
    re.compile(
        r"(?P<ar>[\u0600-\u06FF][\u0600-\u06FF\s\.]+?)\s*\(\s*"
        r"(?P<en>[A-Za-z][A-Za-z\s\-\.]+?)\s*\)"
    ),
)

VALID_MODES = ("hybrid", "structured", "sequential", "contextual")


class BilingualExtractor:
    """Hybrid extractor for (English, Arabic) pairs from raw Telegram text."""

    def __init__(self) -> None:
        self.arabic_range = _ARABIC_RANGE
        self.english_range = _LATIN_RANGE
        self.same_line_patterns = _SAME_LINE_PATTERNS

    # ── Noise pre-cleaning ────────────────────────────────────
    # Patterns that should be stripped from a line before language
    # classification, so that @-mentions / URLs / hashtags don't bias
    # the ratio toward "mostly English".
    _NOISE_PATTERNS = (
        re.compile(r"http\S+|https\S+|www\.\S+"),  # URLs
        re.compile(r"@\w+"),                         # @-mentions
        re.compile(r"#\S+"),                          # hashtags
    )

    def _strip_noise(self, text: str) -> str:
        """Remove URLs, @-mentions, and hashtags from a line."""
        cleaned = text
        for pat in self._NOISE_PATTERNS:
            cleaned = pat.sub("", cleaned)
        return cleaned.strip()

    # ── Language detection helpers ────────────────────────────
    def _is_mostly_arabic(self, text: str) -> bool:
        # Sum of matched-character lengths, NOT the count of matches
        # (``len(findall(...))`` would return the number of regex hits,
        # which is wrong for ratio computation).
        text = self._strip_noise(text)
        ar_chars = sum(len(m) for m in self.arabic_range.findall(text))
        total_alpha = sum(1 for c in text if c.isalpha())
        return (ar_chars / total_alpha) > 0.5 if total_alpha > 0 else False

    def _is_mostly_english(self, text: str) -> bool:
        # The Latin regex greedily includes spaces, so ``len(m)`` may
        # exceed the alphabetic count — that's fine; we only need the
        # ratio to be > 0.5 for the "mostly English" predicate.
        text = self._strip_noise(text)
        en_chars = sum(len(m) for m in self.english_range.findall(text))
        total_alpha = sum(1 for c in text if c.isalpha())
        return (en_chars / total_alpha) > 0.5 if total_alpha > 0 else False

    # ── Main extraction ───────────────────────────────────────
    def extract_pairs(
        self, raw_text: str, mode: str = "hybrid"
    ) -> list[tuple[str, str]]:
        """
        Extract unique (English, Arabic) pairs from ``raw_text``.

        Parameters
        ----------
        raw_text : str
            Raw text from Telegram (one or more messages concatenated by
            blank-line separators).
        mode : str
            One of ``hybrid``, ``structured``, ``sequential``, ``contextual``.

        Returns
        -------
        list of (en, ar) tuples, deduplicated, order preserved.
        """
        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of {VALID_MODES}"
            )

        pairs: set[tuple[str, str]] = set()

        # Split into paragraphs (blocks separated by blank lines).
        blocks = re.split(r"\n\s*\n", raw_text)

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
            if not lines:
                continue

            block_extracted = False

            # Strategy 1: structured (same-line patterns)
            if mode in ("hybrid", "structured"):
                for line in lines:
                    for pattern in self.same_line_patterns:
                        for match in pattern.finditer(line):
                            en = match.group("en").strip()
                            ar = match.group("ar").strip()
                            if len(en) > 1 and len(ar) > 1:
                                pairs.add((en, ar))
                                block_extracted = True

            # Strategy 2: sequential (adjacent lines)
            if (
                mode in ("hybrid", "sequential")
                and not block_extracted
                and len(lines) >= 2
            ):
                for i in range(len(lines) - 1):
                    curr, nxt = lines[i], lines[i + 1]
                    curr_en = self._is_mostly_english(curr) and not self._is_mostly_arabic(curr)
                    curr_ar = self._is_mostly_arabic(curr) and not self._is_mostly_english(curr)
                    nxt_en = self._is_mostly_english(nxt) and not self._is_mostly_arabic(nxt)
                    nxt_ar = self._is_mostly_arabic(nxt) and not self._is_mostly_english(nxt)

                    if curr_en and nxt_ar:
                        pairs.add((curr, nxt))
                        block_extracted = True
                    elif curr_ar and nxt_en:
                        pairs.add((nxt, curr))
                        block_extracted = True

            # Strategy 3: contextual (free-flowing text)
            if mode in ("hybrid", "contextual") and not block_extracted:
                for line in lines:
                    # Strip noise first so @-mentions / URLs / hashtags
                    # don't leak Latin fragments into the contextual pair.
                    cleaned_line = self._strip_noise(line)
                    if not cleaned_line:
                        continue
                    en_runs = [
                        m.group().strip()
                        for m in self.english_range.finditer(cleaned_line)
                        if len(m.group().strip()) > 2
                    ]
                    ar_runs = [
                        m.group().strip()
                        for m in self.arabic_range.finditer(cleaned_line)
                        if len(m.group().strip()) > 2
                    ]
                    if en_runs and ar_runs:
                        # Best-guess: longest Latin run + longest Arabic run.
                        best_en = max(en_runs, key=len)
                        best_ar = max(ar_runs, key=len)
                        pairs.add((best_en, best_ar))

        # Final dedup, preserving first-seen order. Lowercase the English key
        # only for dedup comparison — the stored English text is unchanged.
        valid_pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for en, ar in pairs:
            en_clean = en.strip().rstrip(".,-;:")
            ar_clean = ar.strip().rstrip(".,-;:،؛")
            key = (en_clean.lower(), ar_clean)
            if key not in seen and len(en_clean) > 1 and len(ar_clean) > 1:
                seen.add(key)
                valid_pairs.append((en_clean, ar_clean))

        logger.debug("Extracted %d unique pairs (mode=%s)", len(valid_pairs), mode)
        return valid_pairs

    # ── TSV writer (strict English\tArabic) ───────────────────
    def save_to_tsv(
        self, pairs: list[tuple[str, str]], output_path: str | Path
    ) -> int:
        """
        Save pairs as a strict ``English\\tArabic`` TSV file.

        Only structural cleaning is performed: internal ``\\t``, ``\\n``,
        ``\\r`` characters inside a field are replaced with spaces so they
        don't break TSV column boundaries. The medical text itself is
        preserved verbatim (no normalization of diacritics or alef variants).

        Returns
        -------
        int — number of unique pairs written.
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Dedup while preserving order.
        unique_pairs: list[tuple[str, str]] = list(dict.fromkeys(pairs))

        with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("English\tArabic\n")
            for en, ar in unique_pairs:
                en_clean = (
                    en.replace("\t", " ")
                    .replace("\n", " ")
                    .replace("\r", " ")
                    .strip()
                )
                ar_clean = (
                    ar.replace("\t", " ")
                    .replace("\n", " ")
                    .replace("\r", " ")
                    .strip()
                )
                if en_clean and ar_clean:
                    fh.write(f"{en_clean}\t{ar_clean}\n")

        logger.info("Wrote %d pairs to %s", len(unique_pairs), output_path)
        return len(unique_pairs)

    # ── TSV reader (mirror of save_to_tsv) ────────────────────
    @staticmethod
    def load_from_tsv(tsv_path: str | Path) -> list[tuple[str, str]]:
        """Read a TSV file produced by ``save_to_tsv`` back into pairs."""
        tsv_path = Path(tsv_path)
        pairs: list[tuple[str, str]] = []
        with open(tsv_path, encoding="utf-8") as fh:
            header = fh.readline()
            if not header.strip().startswith("English"):
                # No header — rewind and treat the first line as data.
                fh.seek(0)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    pairs.append((parts[0].strip(), parts[1].strip()))
        return pairs

    # ── Statistics ────────────────────────────────────────────
    def stats(self, pairs: list[tuple[str, str]]) -> dict[str, int]:
        """Return basic stats about an extracted pairs list."""
        total_chars_en = sum(len(en) for en, _ in pairs)
        total_chars_ar = sum(len(ar) for _, ar in pairs)
        return {
            "pairs": len(pairs),
            "unique_en": len({en.lower() for en, _ in pairs}),
            "unique_ar": len({ar for _, ar in pairs}),
            "avg_en_chars": total_chars_en // len(pairs) if pairs else 0,
            "avg_ar_chars": total_chars_ar // len(pairs) if pairs else 0,
        }
