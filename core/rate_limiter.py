"""
core/rate_limiter.py  -  AEGIS PRO v2
Token-bucket rate limiter for exchange API calls.

Usage:
    limiter = RateLimiter(calls_per_second=10)
    await limiter.acquire()    # async
    limiter.acquire_sync()     # sync
"""

import asyncio
import time
import threading
from typing import Optional


class RateLimiter:
    """Thread-safe token-bucket rate limiter (async + sync)."""

    def __init__(self, calls_per_second: float = 10.0, burst: Optional[int] = None):
        self.rate = calls_per_second
        self.capacity = float(burst if burst is not None else max(1, int(calls_per_second)))
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

    def _wait_time(self) -> float:
        self._refill()
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.rate

    def acquire_sync(self) -> None:
        """Block until one token is available (synchronous)."""
        while True:
            with self._lock:
                wait = self._wait_time()
                if wait == 0.0:
                    self._tokens -= 1.0
                    return
            time.sleep(wait)

    async def acquire(self) -> None:
        """Async acquire: yields control while waiting."""
        while True:
            with self._lock:
                wait = self._wait_time()
                if wait == 0.0:
                    self._tokens -= 1.0
                    return
            await asyncio.sleep(wait)

    def try_acquire(self) -> bool:
        """Non-blocking; returns True if token consumed."""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def available_tokens(self) -> float:
        with self._lock:
            self._refill()
            return self._tokens