"""Sliding-window rate limiter for LLM calls.

Blocks *before* calling the provider so free-tier quota is never tripped
mid-demo. Thread-safe via a lock.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, rate_per_minute: int):
        self.rate = max(rate_per_minute, 1)
        self._window = deque()
        self._lock = threading.Lock()

    def acquire(self, timeout: float = 30.0) -> bool:
        """Wait until a slot is free. Returns True when acquired, False on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                now = time.monotonic()
                while self._window and now - self._window[0] > 60.0:
                    self._window.popleft()
                if len(self._window) < self.rate:
                    self._window.append(now)
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def wait(self) -> None:
        if not self.acquire():
            raise TimeoutError("Rate limiter: LLM request throttled (try again shortly).")