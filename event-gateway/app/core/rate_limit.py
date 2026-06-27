from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    reset_after: int


class SlidingWindowRateLimiter:
    """Process-local sliding-window rate limiter.

    This is intentionally lightweight for the exercise. In a horizontally
    scaled deployment, use a shared store or an infrastructure-level limiter.
    """

    def __init__(self, limit: int, window_seconds: float):
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str, now: float | None = None) -> RateLimitDecision:
        current = time.monotonic() if now is None else now
        cutoff = current - self.window_seconds

        with self._lock:
            timestamps = self._requests[key]
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()

            if len(timestamps) >= self.limit:
                retry_after = max(1, math.ceil(timestamps[0] + self.window_seconds - current))
                return RateLimitDecision(
                    allowed=False,
                    limit=self.limit,
                    remaining=0,
                    retry_after=retry_after,
                    reset_after=retry_after,
                )

            timestamps.append(current)
            remaining = max(0, self.limit - len(timestamps))
            reset_after = max(1, math.ceil(timestamps[0] + self.window_seconds - current))
            return RateLimitDecision(
                allowed=True,
                limit=self.limit,
                remaining=remaining,
                retry_after=0,
                reset_after=reset_after,
            )

    def reset(self) -> None:
        with self._lock:
            self._requests.clear()
