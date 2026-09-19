# ADR-0007: Offering both synchronous and asynchronous compose paths

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Product owner, Platform owner

## Context

Compose latency spans two orders of magnitude depending on `detail_level`:

| Detail level | Typical shape | Latency |
|---|---|---|
| `summary` | Short brief from a few chunks | seconds |
| `comprehensive` | Structured multi-section document | tens of seconds |
| `full_deck` | Per-slide narrative across an entire deck | minutes |

One interaction model cannot serve both. Forcing everything synchronous makes
`full_deck` time out behind any normal proxy. Forcing everything asynchronous
makes the interactive UI require polling for a result that would have arrived
before the first poll.

## Decision

Expose both:

- `POST /compose` — synchronous, returns the document and artifacts inline.
- `POST /compose/jobs` — returns `202` with a job id; status and result are
  retrieved from `/compose/jobs/{id}` and `/compose/jobs/{id}/result`.

Both paths run the identical pipeline. Job state is persisted to disk so a
restart does not lose a long-running result.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| Synchronous only | `full_deck` exceeds typical 60s proxy timeouts; the work completes but the client never receives it. |
| Asynchronous only | Adds two round trips and client-side polling to a two-second summary request, for no benefit. |
| Server-sent events / streaming | Good UX for progressive rendering, but the deliverable is a rendered PDF/DOCX, not a token stream. Does not solve durability across a restart. |
| External queue (Celery/RQ) | A broker and worker fleet is disproportionate for the current volume, and would fragment the telemetry path. |

## Consequences

**Positive**

- Each interaction model is served by the appropriate transport.
- One pipeline implementation, so quality and telemetry are identical on both
  paths — there is no "fast path" that skips grounding checks.
- Disk-persisted job snapshots survive restarts and are owner-scoped on read.

**Negative / accepted cost**

- Two public contracts to maintain, document, and test.
- In-process background tasks mean a replica restart can orphan an in-flight
  job; the persisted snapshot records the failure rather than silently hanging.
- Job execution is not distributed — a replica only processes its own jobs.

## Revisit when

Job volume justifies a real queue, or job durability requirements move beyond
"survive a restart" to "survive a node loss".
