"""
Simple in-process rate limiter for LLM calls.

Scoped to authenticated student. Uses a fixed window counter.
Appropriate for personal alpha deployment.
"""

import time
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Configuration for rate limiting."""

    max_requests: int = 30
    window_seconds: int = 60


@dataclass
class RateLimiter:
    """
    Simple in-memory rate limiter.

    Tracks requests per student_id using a fixed window.
    Thread-safe for concurrent requests.
    """

    config: RateLimitConfig = field(default_factory=RateLimitConfig)
    _requests: dict[UUID, list[float]] = field(default_factory=dict, init=False)
    _lock: Lock = field(default_factory=Lock, init=False)

    def check_limit(self, student_id: UUID) -> None:
        """
        Check if the student has exceeded the rate limit.

        Raises:
            RateLimitExceeded: If the limit is exceeded.
        """
        now = time.time()
        window_start = now - self.config.window_seconds

        with self._lock:
            # Clean old entries
            if student_id in self._requests:
                self._requests[student_id] = [
                    ts for ts in self._requests[student_id] if ts > window_start
                ]
            else:
                self._requests[student_id] = []

            # Check limit
            if len(self._requests[student_id]) >= self.config.max_requests:
                oldest = min(self._requests[student_id])
                retry_after = int(oldest + self.config.window_seconds - now) + 1
                raise RateLimitExceeded(
                    f"Rate limit exceeded: {self.config.max_requests} requests per "
                    f"{self.config.window_seconds}s. Retry after {retry_after}s.",
                    retry_after=retry_after,
                )

            # Record this request
            self._requests[student_id].append(now)

    def get_remaining(self, student_id: UUID) -> int:
        """Get remaining requests in current window."""
        now = time.time()
        window_start = now - self.config.window_seconds

        with self._lock:
            if student_id not in self._requests:
                return self.config.max_requests
            current = len(
                [ts for ts in self._requests[student_id] if ts > window_start]
            )
            return max(0, self.config.max_requests - current)


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""

    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.retry_after = retry_after


# Global instance (configured at startup)
rate_limiter: RateLimiter | None = None


def create_rate_limiter(config: RateLimitConfig | None = None) -> RateLimiter:
    """Create and return the global rate limiter instance."""
    global rate_limiter
    rate_limiter = RateLimiter(config or RateLimitConfig())
    return rate_limiter


def get_rate_limiter() -> RateLimiter | None:
    """Get the global rate limiter instance."""
    return rate_limiter
