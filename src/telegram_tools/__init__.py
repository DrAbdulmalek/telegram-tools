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
    TelegramClientMixin,
    TelegramToolsError,
    AuthenticationError,
    ChannelAccessError,
    FloodWaitRetryableError,
)
from .core.rate_limiter import RateLimiter
from .core.copier import TelegramCopier, CopierConfig, CopierResult
from .core.forwarder import (
    TelegramForwarder,
    ForwardConfig,
    ForwardResult,
    MessagePreview,
    create_forwarder,
)
from .core.extractor import TelegramExtractor, CorpusSaver
from .core.preprocess import (
    ArabicNormalizer,
    QualityFilter,
    Deduplicator,
    TextSegmenter,
    CorpusProcessor,
)

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
