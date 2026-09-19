# ADR-0002: Deterministic fallback composer instead of hard failure

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Platform owner, Product owner

## Context

Generation depends on a local inference tier that can be cold, saturated, or
mid-restart. A compose request can also arrive for a model that is not installed.

The naive behaviour is to return HTTP 502. But the user has already paid the
expensive part of the cost: ingestion, parsing, image extraction, and retrieval
all completed successfully. Discarding that work and returning nothing is the
worst possible trade — it converts a degraded result into no result.

## Decision

When generation fails or the model is unavailable, the orchestrator emits a
deterministic, structure-preserving document built from the retrieved grounded
context, marks the run as `degraded` in telemetry, and returns HTTP 200 with the
degradation surfaced in the response.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| Return 502 on any LLM failure | Throws away successful ingestion and retrieval work; makes a transient model restart look like a total outage to the user. |
| Retry until success | Unbounded latency. A cold 8B model load can exceed any reasonable request timeout. |
| Silently degrade with no signal | Unacceptable. An operator cannot distinguish a good run from a fallback run, so quality erodes invisibly. |
| Queue everything asynchronously | Already available via `/compose/jobs`; forcing it for all traffic breaks the interactive UI flow. |

## Consequences

**Positive**

- The service always returns a usable, grounded artifact.
- `degraded_generation_rate` and `fallback_rate` are first-class KPIs, so
  degradation is measured rather than hidden.
- The fallback output doubles as the **quality floor** in the evaluation
  harness: the model must beat it, never fall below it.

**Negative / accepted cost**

- A 200 response no longer implies full-quality generation. Every consumer must
  read the degradation fields, and the dashboard must show the fallback rate
  prominently.
- Tests must explicitly force the LLM path, because a misconfigured test client
  can silently exercise the fallback and still look green.

## Revisit when

`fallback_rate` exceeds 5% of production traffic — at that point the correct fix
is inference capacity, not a better fallback.
