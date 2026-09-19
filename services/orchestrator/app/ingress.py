"""Ingress protection for the orchestrator.

A single ``/compose`` call can hold a worker for tens of seconds while it parses
a deck, runs retrieval, and streams an LLM response. That makes the service easy
to starve, so requests are gated *before* they reach the generation pipeline:

* :class:`RateLimiter` enforces a per-identity sliding window.
* :func:`oversized_request_bytes` rejects oversized bodies with HTTP 413.

Both controls are deliberately in-process. The service scales horizontally
behind a shared ingress, so this is a per-replica backstop that protects worker
capacity; a distributed quota belongs in the API gateway (see
``docs/adr/0004-in-process-rate-limiting.md``).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single limiter check."""

    allowed: bool
    limit: int
    remaining: int
    retry_after_seconds: int


class RateLimiter:
    """Thread-safe sliding-window rate limiter keyed by caller identity.

    A sliding window is used instead of a fixed window because fixed windows
    allow a 2x burst across a boundary, which for this workload means double the
    expensive generation calls arriving at once.
    """

    _SWEEP_THRESHOLD = 1024

    def __init__(self, requests_per_minute: int, burst: int = 0, window_seconds: float = 60.0) -> None:
        self._capacity = max(requests_per_minute, 0) + max(burst, 0)
        self._requests_per_minute = max(requests_per_minute, 0)
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._requests_per_minute > 0

    def check(self, key: str, *, now: float | None = None) -> RateLimitDecision:
        """Record an attempt for ``key`` and report whether it is permitted."""
        if not self.enabled:
            return RateLimitDecision(allowed=True, limit=0, remaining=0, retry_after_seconds=0)

        timestamp = time.monotonic() if now is None else now
        cutoff = timestamp - self._window_seconds

        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and window[0] <= cutoff:
                window.popleft()

            if len(window) >= self._capacity:
                retry_after = max(int(window[0] + self._window_seconds - timestamp) + 1, 1)
                return RateLimitDecision(
                    allowed=False,
                    limit=self._capacity,
                    remaining=0,
                    retry_after_seconds=retry_after,
                )

            window.append(timestamp)
            if len(self._hits) > self._SWEEP_THRESHOLD:
                self._sweep(cutoff)

            return RateLimitDecision(
                allowed=True,
                limit=self._capacity,
                remaining=max(self._capacity - len(window), 0),
                retry_after_seconds=0,
            )

    def _sweep(self, cutoff: float) -> None:
        """Drop identities with no activity inside the window.

        Called under the lock and only once the key count crosses a threshold,
        so steady-state traffic pays no cleanup cost.
        """
        stale = [key for key, window in self._hits.items() if not window or window[-1] <= cutoff]
        for key in stale:
            self._hits.pop(key, None)

    def reset(self) -> None:
        """Drop all tracked windows. Used by tests and after config reloads."""
        with self._lock:
            self._hits.clear()


def client_key(user_id: str | None, client_host: str | None) -> str:
    """Derive the limiter key.

    Identity is preferred over network address so that a single misbehaving user
    cannot be masked by a shared NAT egress IP, and so quota follows the caller
    across replicas of the same client.
    """
    if user_id and user_id.strip():
        return f"user:{user_id.strip()}"
    return f"ip:{client_host or 'unknown'}"


def oversized_request_bytes(content_length: str | None, max_bytes: int) -> int | None:
    """Return the declared body size when it exceeds ``max_bytes``, else ``None``."""
    if max_bytes <= 0 or not content_length:
        return None

    try:
        declared = int(content_length)
    except (TypeError, ValueError):
        return None

    return declared if declared > max_bytes else None
