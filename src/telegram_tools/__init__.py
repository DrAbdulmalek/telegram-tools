"""
Telegram Tools — Unified toolkit for Telegram channel operations.

Combines three previously-separate utilities into one cohesive package:
  - Copier   : fast bulk copy between channels (no media re-download)
  - Forwarder: bypass "Restrict Saving Content" via Download-Upload
  - Extractor: build NLP/OCR-ready corpora from channel history
  - Preprocess: Arabic normalization, dedup, quality filtering, segmentation
"""

__version__ = "1.1.0"
__author__ = "Abdulmalek Husseini"

from .core.base import (
    AuthenticationError,
    ChannelAccessError,
    FloodWaitRetryableError,
    TelegramClientMixin,
    TelegramToolsError,
)
from .core.copier import CopierConfig, CopierResult, TelegramCopier
from .core.extractor import CorpusSaver, TelegramExtractor
from .core.forwarder import (
    ForwardConfig,
    ForwardResult,
    MessagePreview,
    TelegramForwarder,
    create_forwarder,
)
from .core.preprocess import (
    ArabicNormalizer,
    CorpusProcessor,
    Deduplicator,
    QualityFilter,
    TextSegmenter,
)
from .core.rate_limiter import RateLimiter

__all__ = [
    "__version__",
    "__author__",
    # base
    "TelegramClientMixin",
    "TelegramToolsError",
    "AuthenticationError",
    "ChannelAccessError",
    "FloodWaitRetryableError",
    # rate_limiter
    "RateLimiter",
    # copier
    "TelegramCopier",
    "CopierConfig",
    "CopierResult",
    # forwarder
    "TelegramForwarder",
    "ForwardConfig",
    "ForwardResult",
    "MessagePreview",
    "create_forwarder",
    # extractor
    "TelegramExtractor",
    "CorpusSaver",
    # preprocess
    "ArabicNormalizer",
    "QualityFilter",
    "Deduplicator",
    "TextSegmenter",
    "CorpusProcessor",
]
