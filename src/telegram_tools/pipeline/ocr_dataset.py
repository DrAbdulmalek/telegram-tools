"""
PyTorch ``Dataset`` for medical OCR (image → text).

Pairs images downloaded from Telegram (by ``TelegramExtractor``) with their
accompanying text caption to serve as ground-truth for Vision-Encoder-Decoder
models such as Microsoft TrOCR or Donut.

The expected on-disk layout (produced by ``TelegramExtractor``)::

    output_dir/
      media/
        images/         # *.jpg / *.png / *.webp
      metadata.jsonl    # one JSON entry per message:
                        # {"msg_id": 123, "text": "...", "has_media": true, ...}

Supported processors
--------------------
- ``microsoft/trocr-base-printed``
- ``microsoft/trocr-base-handwritten``
- Any ``AutoProcessor``-compatible Vision-Encoder-Decoder.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

try:
    import torch
    from torch.utils.data import Dataset
    from transformers import AutoProcessor
    from PIL import Image
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None  # type: ignore
    Dataset = object  # type: ignore
    AutoProcessor = None  # type: ignore
    Image = None  # type: ignore


class MedicalOCRDataset(Dataset):
    """Image-to-text dataset for medical OCR training.

    Parameters
    ----------
    images_dir : path-like
        Directory containing image files (``msg_id.jpg`` etc.).
    metadata_file : path-like
        JSONL file produced by ``TelegramExtractor``. Each line is a JSON
        object with at least ``msg_id``, ``text``, and ``has_media``.
    processor_name : str
        HuggingFace model ID for the processor (TrOCR family recommended).
    max_length : int
        Maximum label length. Longer texts are truncated.
    """

    SUPPORTED_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")

    def __init__(
        self,
        images_dir: str | Path,
        metadata_file: str | Path,
        processor_name: str = "microsoft/trocr-base-printed",
        max_length: int = 512,
    ) -> None:
        if not _TORCH_AVAILABLE:
            raise ImportError(
                "torch, transformers, and Pillow are required for MedicalOCRDataset. "
                "Install with: pip install torch transformers Pillow"
            )

        self.images_dir = Path(images_dir)
        self.metadata_file = Path(metadata_file)
        self.processor_name = processor_name
        self.max_length = max_length

        if not self.images_dir.is_dir():
            raise FileNotFoundError(f"Images dir not found: {self.images_dir}")
        if not self.metadata_file.is_file():
            raise FileNotFoundError(f"Metadata file not found: {self.metadata_file}")

        self.processor = AutoProcessor.from_pretrained(processor_name)
        self.samples: List[Dict[str, object]] = self._load_metadata()

        logger.info(
            "Loaded %d OCR samples from %s (processor=%s)",
            len(self.samples),
            self.metadata_file,
            processor_name,
        )

    def _load_metadata(self) -> List[Dict[str, object]]:
        """Read metadata.jsonl and pair each image with its caption."""
        samples: List[Dict[str, object]] = []
        with open(self.metadata_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                text = (data.get("text") or "").strip()
                msg_id = data.get("msg_id")
                if not text or len(text) < 5 or msg_id is None:
                    continue
                if not data.get("has_media"):
                    continue

                # Find the actual image file (extension-agnostic).
                image_path = self._find_image(msg_id)
                if image_path is None:
                    continue

                samples.append({
                    "image_path": image_path,
                    "text": text,  # Verbatim — zero medical normalization.
                    "msg_id": msg_id,
                })
        return samples

    def _find_image(self, msg_id) -> Path | None:
        """Locate ``{msg_id}.{ext}`` in ``images_dir`` for any supported ext."""
        for ext in self.SUPPORTED_IMAGE_EXTS:
            candidate = self.images_dir / f"{msg_id}{ext}"
            if candidate.exists():
                return candidate
        return None

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> Dict[str, object]:
        sample = self.samples[idx]
        image = Image.open(sample["image_path"]).convert("RGB")

        # Pixel values from the image processor.
        pixel_values = self.processor(
            images=image, return_tensors="pt"
        ).pixel_values.squeeze()

        # Tokenize the caption into labels.
        labels = self.processor.tokenizer(
            sample["text"],
            max_length=self.max_length,
            padding="max_length",
            truncation=True,
            return_tensors="pt",
        ).input_ids.squeeze()

        # Mask padding out of the loss.
        labels[labels == self.processor.tokenizer.pad_token_id] = -100

        return {
            "pixel_values": pixel_values,
            "labels": labels,
            "raw_text": sample["text"],
            "msg_id": sample["msg_id"],
        }
