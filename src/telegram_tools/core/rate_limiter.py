"""
Dynamic rate limiter — exponential backoff on FloodWait.

A fixed delay between messages is fragile: too low and Telegram bans you,
too high and a 10k-message channel takes days. We start with the caller's
requested base delay and double it on every FloodWait, capping at 60s.
After a streak of successful sends, we relax back toward the base delay.
"""

from __future__ import annotations


class RateLimiter:
    """Adaptive delay calculator with exponential backoff on FloodWait."""

    MAX_DELAY = 60.0
    RELAX_AFTER_SUCCESSES = 10

    def __init__(self, base_delay: float = 2.0):
        if base_delay < 0:
            raise ValueError("base_delay must be non-negative")
        self.base_delay = base_delay
        self._flood_count = 0
        self._success_streak = 0

    def get_delay(self) -> float:
        """Return the recommended delay for the next send."""
        if self._flood_count == 0:
            return self.base_delay
        return min(self.base_delay * (2 ** self._flood_count), self.MAX_DELAY)

    def record_flood(self, wait_seconds: int) -> float:
        """
        Called when Telegram returns FloodWaitError.

        Returns the recommended sleep duration — always the larger of
        what Telegram asked for and what our backoff would suggest.
        """
        self._flood_count += 1
        self._success_streak = 0
        return max(float(wait_seconds), self.get_delay())

    def record_success(self) -> None:
        """Called after a successful send — relaxes the delay back down."""
        self._success_streak += 1
        if self._success_streak >= self.RELAX_AFTER_SUCCESSES and self._flood_count > 0:
            self._flood_count = max(0, self._flood_count - 1)
            self._success_streak = 0

    def reset(self) -> None:
        """Reset all counters — used at the start of a new operation."""
        self._flood_count = 0
        self._success_streak = 0

    @property
    def state(self) -> dict:
        """Snapshot for logging / UI display."""
        return {
            "base_delay": self.base_delay,
            "current_delay": self.get_delay(),
            "flood_count": self._flood_count,
            "success_streak": self._success_streak,
        }
