"""Core modules for telegram_tools."""

from .base import (
    AuthenticationError,
    ChannelAccessError,
    FloodWaitRetryableError,
    TelegramClientMixin,
    TelegramToolsError,
)
from .client_manager import TelegramClientManager
from .copier import CopierConfig, CopierResult, TelegramCopier
from .extractor import CorpusSaver, TelegramExtractor
from .forwarder import (
    ForwardConfig,
    ForwardResult,
    MessagePreview,
    TelegramForwarder,
    create_forwarder,
)
from .preprocess import (
    ArabicNormalizer,
    CorpusProcessor,
    Deduplicator,
    QualityFilter,
    TextSegmenter,
)
from .rate_limiter import RateLimiter
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
