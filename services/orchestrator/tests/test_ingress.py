"""Tests for ingress protection: rate limiting and request size guards.

These cover the controls that keep a single caller from exhausting the worker
pool. They are unit-level on the limiter (deterministic clock) plus integration
level through the ASGI stack so the middleware wiring is actually exercised.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.ingress import RateLimiter, client_key, oversized_request_bytes

# ---------------------------------------------------------------------------
# RateLimiter unit behaviour
# ---------------------------------------------------------------------------


def test_limiter_allows_traffic_up_to_capacity() -> None:
    limiter = RateLimiter(requests_per_minute=3, burst=0)

    decisions = [limiter.check("user:a", now=100.0 + i) for i in range(3)]

    assert all(decision.allowed for decision in decisions)
    assert decisions[-1].remaining == 0


def test_limiter_blocks_once_capacity_is_exhausted() -> None:
    limiter = RateLimiter(requests_per_minute=2, burst=0)
    for i in range(2):
        limiter.check("user:a", now=100.0 + i)

    decision = limiter.check("user:a", now=102.0)

    assert decision.allowed is False
    assert decision.remaining == 0
    assert decision.retry_after_seconds > 0


def test_limiter_window_slides_so_old_hits_expire() -> None:
    limiter = RateLimiter(requests_per_minute=2, burst=0, window_seconds=60.0)
    limiter.check("user:a", now=0.0)
    limiter.check("user:a", now=1.0)

    assert limiter.check("user:a", now=30.0).allowed is False
    # Both original hits have aged out of the 60s window by t=62.
    assert limiter.check("user:a", now=62.0).allowed is True


def test_burst_extends_capacity_above_the_steady_rate() -> None:
    limiter = RateLimiter(requests_per_minute=2, burst=2)

    allowed = [limiter.check("user:a", now=float(i)).allowed for i in range(5)]

    assert allowed == [True, True, True, True, False]


def test_quota_is_isolated_per_identity() -> None:
    limiter = RateLimiter(requests_per_minute=1, burst=0)
    limiter.check("user:a", now=0.0)

    assert limiter.check("user:a", now=1.0).allowed is False
    assert limiter.check("user:b", now=1.0).allowed is True


def test_limiter_is_disabled_when_rate_is_zero() -> None:
    limiter = RateLimiter(requests_per_minute=0, burst=0)

    assert limiter.enabled is False
    assert all(limiter.check("user:a", now=float(i)).allowed for i in range(50))


def test_stale_identities_are_swept_to_bound_memory() -> None:
    limiter = RateLimiter(requests_per_minute=5, burst=0, window_seconds=60.0)
    for index in range(RateLimiter._SWEEP_THRESHOLD + 5):
        limiter.check(f"user:{index}", now=0.0)

    # A much later request triggers the sweep; the ancient keys must be dropped.
    limiter.check("user:recent", now=10_000.0)

    assert len(limiter._hits) < RateLimiter._SWEEP_THRESHOLD


def test_client_key_prefers_identity_over_network_address() -> None:
    assert client_key("user-1", "10.0.0.5") == "user:user-1"
    assert client_key(None, "10.0.0.5") == "ip:10.0.0.5"
    assert client_key("   ", "10.0.0.5") == "ip:10.0.0.5"
    assert client_key(None, None) == "ip:unknown"


# ---------------------------------------------------------------------------
# Request size guard
# ---------------------------------------------------------------------------


def test_oversized_request_detection() -> None:
    assert oversized_request_bytes("100", 50) == 100
    assert oversized_request_bytes("10", 50) is None
    assert oversized_request_bytes(None, 50) is None
    assert oversized_request_bytes("not-a-number", 50) is None
    # A limit of zero disables the guard entirely.
    assert oversized_request_bytes("999999", 0) is None


# ---------------------------------------------------------------------------
# Middleware integration through the real ASGI stack
# ---------------------------------------------------------------------------


def test_oversized_payload_is_rejected_before_reaching_the_pipeline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_request_bytes", 64)
    client = TestClient(main.app)

    response = client.post(
        "/compose",
        json={"document_id": "d", "user_prompt": "x" * 500, "source_text": "y" * 500},
        headers={"X-User-Id": "user-1", "X-User-Role": "author"},
    )

    assert response.status_code == 413
    assert response.json()["max_request_bytes"] == 64


def test_rate_limited_requests_return_429_with_retry_headers(monkeypatch) -> None:
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(requests_per_minute=1, burst=0))
    client = TestClient(main.app)
    headers = {"X-User-Id": "rate-test-user", "X-User-Role": "author"}

    first = client.get("/capabilities", headers=headers)
    second = client.get("/capabilities", headers=headers)

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "1"
    assert second.status_code == 429
    assert int(second.headers["Retry-After"]) >= 1


def test_probe_endpoints_are_exempt_from_rate_limiting(monkeypatch) -> None:
    monkeypatch.setattr(main, "rate_limiter", RateLimiter(requests_per_minute=1, burst=0))
    client = TestClient(main.app)

    statuses = [client.get("/healthz").status_code for _ in range(5)]

    assert statuses == [200] * 5
