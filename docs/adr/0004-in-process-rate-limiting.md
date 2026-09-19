# ADR-0004: In-process rate limiting as a per-replica backstop

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Platform owner

## Context

A single `/compose` call occupies a worker for tens of seconds: deck parsing,
image extraction, retrieval, and a multi-second LLM round trip. With
`UVICORN_WORKERS=2`, three concurrent abusive requests are enough to make the
service unresponsive to everyone else — including its own health probes.

Protection was required before generation begins, not after.

## Decision

Enforce a per-identity sliding-window limit inside the ASGI middleware stack,
keyed by `X-User-Id` and falling back to client IP. The limiter is explicitly a
**per-replica backstop**, not a global quota.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| Redis-backed distributed limiter | Adds a stateful dependency and a network hop to the hot path purely to protect against a failure mode the gateway should own. Not worth the operational surface. |
| Gateway/ingress rate limiting only | Correct long-term home, but leaves the service defenceless when run standalone, in Compose, or during a gateway misconfiguration. |
| Fixed-window counter | Allows a 2x burst across the window boundary — for this workload that is double the expensive generation calls arriving simultaneously. |
| Concurrency semaphore instead of a rate limit | Bounds parallelism but not total consumption; one caller can still monopolise the queue indefinitely. |

## Consequences

**Positive**

- Works identically in local dev, Compose, and Kubernetes with no extra
  infrastructure.
- Keyed on identity, so a shared NAT egress IP does not let one user hide behind
  another, and quota follows the caller across client instances.
- Health and metrics endpoints are exempt, so a limited service is still
  observable and still passes probes.
- Returns `Retry-After` and `X-RateLimit-*`, so clients can back off correctly.

**Negative / accepted cost**

- The effective global limit is `limit x replica_count`. This is documented, and
  the per-replica value is set with the replica count in mind.
- Limiter state is lost on restart, briefly resetting quotas. Acceptable for a
  backstop.
- Memory grows with distinct identities; bounded by a sweep of stale windows
  once the key count crosses a threshold.

## Revisit when

A shared API gateway is introduced, at which point this becomes defence in depth
and the authoritative quota moves to the gateway.
