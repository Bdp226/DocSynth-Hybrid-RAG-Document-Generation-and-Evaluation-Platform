# ADR-0006: In-process telemetry registry instead of the OpenTelemetry SDK

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Platform owner, ML owner

## Context

The KPIs that matter here are not generic RED metrics. They are
domain-specific and computed *from the generated document*: groundedness,
hallucination rate, figure retention, leakage counts, schema compliance,
coverage, nDCG@10. These are derived once per compose run, at the end of the
pipeline, from data that only exists at that moment.

An OpenTelemetry metrics pipeline is built for high-frequency, low-cardinality
instrument updates scattered across a codebase. It is a poor fit for "emit one
50-field quality record per request" and would still require a custom
computation layer to produce the fields.

## Decision

Use a purpose-built `MetricsRegistry` that records one `RunMetrics` record per
compose run, keeps a bounded in-memory window for aggregation, appends to a
JSONL log for offline analysis, and exposes both a JSON snapshot and Prometheus
text exposition.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| OpenTelemetry metrics SDK | Adds a dependency and a collector for a workload that is one record per request; still needs custom code to compute every domain KPI. |
| `prometheus_client` library | Reasonable, but the aggregate-quality view (percentiles, ratios, triage breakdowns) is not naturally expressible as counters and histograms without flattening the per-run record that offline analysis depends on. |
| Ship raw logs and compute everything downstream | Requires a log pipeline to exist before any KPI is visible, and makes `/metrics` and the built-in dashboard impossible. |

## Consequences

**Positive**

- One record per run is both the dashboard source and the offline analysis
  dataset — no divergence between what is displayed and what is analysed.
- Zero additional infrastructure: `/metrics` is scrapeable by Prometheus today
  via the standard exposition format and pod annotations.
- Telemetry capture is wrapped and best-effort; it can never fail a request.

**Negative / accepted cost**

- **No distributed tracing.** Request IDs are generated and propagated, but
  there is no span export, so a slow run cannot be broken down across services.
  This is the single largest observability gap and is accepted only because the
  system is currently one service plus two dependencies.
- The in-memory window is bounded at 500 runs, so `/metrics` reflects recent
  behaviour rather than all history. Long-range analysis uses the JSONL log.
- Metrics are per replica; aggregation across replicas is Prometheus's job.

## Revisit when

A second first-party service is added to the request path, at which point
OpenTelemetry tracing becomes necessary and this registry should export through
it rather than be replaced by it.
