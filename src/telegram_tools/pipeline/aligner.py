"""
Backward-compatible alias for :mod:`bilingual_extractor`.

Older code and the original Mistral/DeepSeek drafts used the name
``BilingualAligner``. We re-export the same class under both names so
that downstream code keeps working.
"""

from .bilingual_extractor import BilingualExtractor


class BilingualAligner(BilingualExtractor):
    """Alias for :class:`BilingualExtractor` — kept for API compatibility."""

    __doc__ = BilingualExtractor.__doc__


__all__ = ["BilingualAligner", "BilingualExtractor"]
