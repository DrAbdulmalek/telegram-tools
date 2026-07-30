"""
Bilingual corpus pipeline — extraction, alignment, splitting, and ML packaging.

Modules
-------
- ``bilingual_extractor`` — Hybrid (English <-> Arabic) extractor with
  three strategies: structured (same-line), sequential (adjacent lines),
  and contextual (free-flowing text). Zero medical normalization.
- ``aligner`` — Convenience alias re-exporting ``BilingualExtractor``.
- ``splitter`` — Train/Val/Test splitter with deterministic shuffle to
  break alphabetical bias in dictionary corpora.
- ``pytorch_dataset`` — ``MedicalBilingualDataset`` for Seq2Seq training
  (NLLB / mBART / MarianMT).
- ``ocr_dataset`` — ``MedicalOCRDataset`` for Vision-Encoder-Decoder
  training (TrOCR / Donut).
- ``hf_uploader`` — One-click dataset publisher to HuggingFace Hub
  (private or public).
"""

from .bilingual_extractor import BilingualExtractor
from .splitter import DatasetSplitter
from .pytorch_dataset import MedicalBilingualDataset
from .hf_uploader import HuggingFaceUploader

__all__ = [
    "BilingualExtractor",
    "DatasetSplitter",
    "MedicalBilingualDataset",
    "HuggingFaceUploader",
]

__version__ = "1.1.0"
