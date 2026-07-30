"""
PyTorch ``Dataset`` for bilingual medical glossaries.

Reads a TSV file produced by ``BilingualExtractor.save_to_tsv`` and emits
``input_ids`` / ``attention_mask`` / ``labels`` ready for ``Seq2SeqTrainer``.

Supported tokenizers
--------------------
- ``facebook/nllb-200-distilled-600M`` (recommended — 200 languages)
- ``facebook/mbart-large-50``
- ``Helsinki-NLP/opus-mt-en-ar``
- Any ``AutoTokenizer``-compatible Seq2Seq tokenizer.

The raw medical text is preserved as ``raw_en`` / ``raw_ar`` fields inside
each item to facilitate debugging and human review.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Heavy imports are deferred so the module can be imported in environments
# without torch/transformers (e.g. when running only the extractor).
try:
    import torch
    from torch.utils.data import Dataset
    from transformers import AutoTokenizer
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore
    Dataset = object  # type: ignore
    AutoTokenizer = None  # type: ignore


# Default NLLB-200 language codes.
_DEFAULT_SRC_LANG = "eng_Latn"
_DEFAULT_TGT_LANG = "arb_Arab"


class MedicalBilingualDataset(Dataset):
    """PyTorch ``Dataset`` for bilingual medical glossaries.

    The dataset is read once on construction and held in memory as a list
    of (en, ar) tuples. ``__getitem__`` performs tokenization on demand.

    Parameters
    ----------
    tsv_path : path-like
        TSV file with header ``English\\tArabic``.
    tokenizer_name : str
        HuggingFace model ID (e.g. ``facebook/nllb-200-distilled-600M``).
    max_length : int
        Maximum token length per sample. Longer samples are truncated.
    source_lang, target_lang : str
        NLLB/mBART language codes. Ignored for tokenizers that don't use them.
    """

    def __init__(
        self,
        tsv_path: str | Path,
        tokenizer_name: str = "facebook/nllb-200-distilled-600M",
        max_length: int = 128,
        source_lang: str = _DEFAULT_SRC_LANG,
        target_lang: str = _DEFAULT_TGT_LANG,
    ) -> None:
        if not _TORCH_AVAILABLE:
            raise ImportError(
                "torch and transformers are required for MedicalBilingualDataset. "
                "Install with: pip install torch transformers"
            )

        self.tsv_path = Path(tsv_path)
        if not self.tsv_path.exists():
            raise FileNotFoundError(f"TSV file not found: {self.tsv_path}")

        self.tokenizer_name = tokenizer_name
        self.max_length = max_length
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)

        # NLLB and mBART need explicit src/tgt language codes.
        name_lower = tokenizer_name.lower()
        if "nllb" in name_lower or "mbart" in name_lower:
            try:
                self.tokenizer.src_lang = source_lang
                self.tokenizer.tgt_lang = target_lang
            except Exception:  # pragma: no cover
                logger.warning(
                    "Could not set src_lang/tgt_lang on %s — "
                    "tokenizer may not support language codes.",
                    tokenizer_name,
                )

        self.pairs: list[tuple[str, str]] = self._load_tsv(self.tsv_path)
        logger.info(
            "Loaded %d pairs from %s (tokenizer=%s, max_length=%d)",
            len(self.pairs),
            self.tsv_path,
            tokenizer_name,
            max_length,
        )

    @staticmethod
    def _load_tsv(path: Path) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        with open(path, encoding="utf-8") as fh:
            header = fh.readline()
            if not header.strip().startswith("English"):
                fh.seek(0)
            for line in fh:
                parts = line.rstrip("\n").split("\t")
                if len(parts) == 2 and parts[0].strip() and parts[1].strip():
                    pairs.append((parts[0].strip(), parts[1].strip()))
        return pairs

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> dict[str, object]:
        en_text, ar_text = self.pairs[idx]

        source_encoding = self.tokenizer(
            en_text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )
        target_encoding = self.tokenizer(
            ar_text,
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        )

        labels = target_encoding["input_ids"].squeeze()
        # Mask padding tokens out of the loss computation.
        labels[labels == self.tokenizer.pad_token_id] = -100

        return {
            "input_ids": source_encoding["input_ids"].squeeze(),
            "attention_mask": source_encoding["attention_mask"].squeeze(),
            "labels": labels,
            # Raw strings kept for debugging / human review.
            "raw_en": en_text,
            "raw_ar": ar_text,
        }

    # ── Preview helper ────────────────────────────────────────
    def preview(self, n_samples: int = 3) -> str:
        """Return a human-readable preview of how the tokenizer sees the data."""
        if n_samples <= 0:
            return ""

        lines: list[str] = []
        for i in range(min(n_samples, len(self.pairs))):
            item = self[i]
            input_ids = item["input_ids"]
            labels = item["labels"]

            # Filter out padding / -100 labels for the preview.
            valid_label_ids = labels[labels != -100]
            en_tokens = self.tokenizer.convert_ids_to_tokens(input_ids)
            ar_tokens = self.tokenizer.convert_ids_to_tokens(valid_label_ids)

            lines.append(f"Sample {i + 1}:")
            lines.append(f"  📝 EN (raw):  {item['raw_en']}")
            lines.append(f"  🔤 EN tokens: {en_tokens[:10]}{'...' if len(en_tokens) > 10 else ''}  (total: {len(en_tokens)})")
            lines.append(f"  📝 AR (raw):  {item['raw_ar']}")
            lines.append(f"  🔤 AR tokens: {ar_tokens[:10]}{'...' if len(ar_tokens) > 10 else ''}  (total: {len(ar_tokens)})")
            lines.append("-" * 60)
        return "\n".join(lines)
