"""
Train/Val/Test splitter for bilingual dictionary corpora.

Medical dictionaries are typically sorted alphabetically (A→Z). A naive
sequential split would put A-S in train and T-Z in test, leaving the model
blind to letters it never saw during training. This module shuffles the
pairs deterministically (seeded) before splitting to break that bias.

Output formats
--------------
- ``tsv``   — strict ``English\\tArabic`` (PyTorch custom ``Dataset``)
- ``jsonl`` — HuggingFace ``datasets`` format: ``{"translation": {"en": ..., "ar": ...}}``
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path

logger = logging.getLogger(__name__)


class DatasetSplitter:
    """Deterministic train/val/test splitter with shuffle to break
    alphabetical bias in dictionary corpora."""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    def split_data(
        self,
        pairs: list[tuple[str, str]],
        train_ratio: float,
        val_ratio: float,
    ) -> dict[str, list[tuple[str, str]]]:
        """
        Shuffle ``pairs`` deterministically and split into train/val/test.

        Parameters
        ----------
        pairs : list of (en, ar)
        train_ratio : float in (0, 1)
        val_ratio : float in (0, 1)
            ``train_ratio + val_ratio`` must be < 1.0; the remainder goes
            to test.

        Returns
        -------
        dict with keys ``train``, ``val``, ``test``.
        """
        if train_ratio + val_ratio >= 1.0:
            raise ValueError(
                f"train_ratio ({train_ratio}) + val_ratio ({val_ratio}) "
                f"must be < 1.0"
            )
        if train_ratio <= 0 or val_ratio <= 0:
            raise ValueError("Ratios must be > 0")

        rng = random.Random(self.seed)
        shuffled = list(pairs)
        rng.shuffle(shuffled)

        n = len(shuffled)
        n_train = int(n * train_ratio)
        n_val = int(n * val_ratio)

        return {
            "train": shuffled[:n_train],
            "val": shuffled[n_train : n_train + n_val],
            "test": shuffled[n_train + n_val :],
        }

    def save_splits(
        self,
        splits: dict[str, list[tuple[str, str]]],
        output_dir: str | Path,
        file_format: str = "tsv",
    ) -> dict[str, str]:
        """
        Persist ``splits`` to ``output_dir``.

        Parameters
        ----------
        splits : dict from ``split_data``
        output_dir : path-like
        file_format : ``"tsv"`` or ``"jsonl"``

        Returns
        -------
        dict mapping split name → absolute file path.
        """
        if file_format not in ("tsv", "jsonl"):
            raise ValueError(f"Unsupported format: {file_format}")

        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        saved_files: dict[str, str] = {}

        for split_name, data in splits.items():
            if file_format == "tsv":
                file_path = out_path / f"{split_name}.tsv"
                with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write("English\tArabic\n")
                    for en, ar in data:
                        # Structural cleaning only.
                        en_clean = en.replace("\t", " ").replace("\n", " ").strip()
                        ar_clean = ar.replace("\t", " ").replace("\n", " ").strip()
                        if en_clean and ar_clean:
                            fh.write(f"{en_clean}\t{ar_clean}\n")
            else:  # jsonl
                file_path = out_path / f"{split_name}.jsonl"
                with open(file_path, "w", encoding="utf-8", newline="\n") as fh:
                    for en, ar in data:
                        en_clean = en.replace("\n", " ").replace("\r", " ").strip()
                        ar_clean = ar.replace("\n", " ").replace("\r", " ").strip()
                        record = {"translation": {"en": en_clean, "ar": ar_clean}}
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

            saved_files[split_name] = str(file_path)
            logger.info("Wrote %s split: %d pairs → %s", split_name, len(data), file_path)

        return saved_files

    def summary(self, splits: dict[str, list[tuple[str, str]]]) -> str:
        """Human-readable summary of a splits dict."""
        total = sum(len(v) for v in splits.values())
        lines = [f"Total pairs: {total} (shuffled with seed={self.seed})"]
        for name in ("train", "val", "test"):
            if name in splits:
                count = len(splits[name])
                pct = (count / total * 100) if total else 0
                lines.append(f"  {name:5s}: {count:6d} ({pct:5.1f}%)")
        return "\n".join(lines)
