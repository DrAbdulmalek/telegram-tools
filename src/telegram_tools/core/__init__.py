"""Core modules for telegram_tools."""

from .base import (
    TelegramClientMixin,
    TelegramToolsError,
    AuthenticationError,
    ChannelAccessError,
    FloodWaitRetryableError,
)
from .client_manager import TelegramClientManager
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
from .telegram_bridge import TelegramBridge

__all__ = [
    "TelegramClientMixin",
    "TelegramClientManager",
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
    "TelegramBridge",
]
