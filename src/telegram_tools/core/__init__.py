"""Core modules for telegram_tools."""

from .base import (
    TelegramClientMixin,
    TelegramToolsError,
    AuthenticationError,
    ChannelAccessError,
    FloodWaitRetryableError,
)
from .rate_limiter import RateLimiter
from .copier import TelegramCopier, CopierConfig, CopierResult
from .forwarder import (
    TelegramForwarder,
    ForwardConfig,
    ForwardResult,
    MessagePreview,
    create_forwarder,
)
from .extractor import TelegramExtractor, CorpusSaver
from .preprocess import (
    ArabicNormalizer,
    QualityFilter,
    Deduplicator,
    TextSegmenter,
    CorpusProcessor,
)

__all__ = [
    "TelegramClientMixin",
    "TelegramToolsError",
    "AuthenticationError",
    "ChannelAccessError",
    "FloodWaitRetryableError",
    "RateLimiter",
    "TelegramCopier",
    "CopierConfig",
    "CopierResult",
    "TelegramForwarder",
    "ForwardConfig",
    "ForwardResult",
    "MessagePreview",
    "create_forwarder",
    "TelegramExtractor",
    "CorpusSaver",
    "ArabicNormalizer",
    "QualityFilter",
    "Deduplicator",
    "TextSegmenter",
    "CorpusProcessor",
]
