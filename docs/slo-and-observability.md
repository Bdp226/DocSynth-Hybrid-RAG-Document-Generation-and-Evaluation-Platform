# SLOs, Observability, and Alerting

This document defines what "healthy" means for DocSynth in numbers, how it is
measured, and what happens when it is not met.

---

## 1. Service Level Indicators

Every SLI is derived from data the service already emits — the per-run
`RunMetrics` record and the request middleware — so nothing here requires new
instrumentation to measure.

| # | SLI | Definition | Source |
|---|---|---|---|
| 1 | **Availability** | Non-5xx responses ÷ total responses | request middleware |
| 2 | **Delivery success** | Compose runs producing at least one artifact ÷ total compose runs | `documents_delivered`, `success_rate` |
| 3 | **Summary latency** | p95 wall time for `detail_level=summary` | `latency_p95_ms` |
| 4 | **Comprehensive latency** | p95 wall time for `detail_level=comprehensive` | `latency_p95_ms` |
| 5 | **Full-deck latency** | p95 wall time for `detail_level=full_deck` | `latency_p95_ms` |
| 6 | **Generation integrity** | Runs with zero leak detections ÷ total runs | `content_integrity_pass`, `leak_counts` |
| 7 | **Groundedness** | Mean `groundedness_score` across runs | `compute_genai_quality_metrics` |
| 8 | **Degradation rate** | Runs served by the deterministic fallback ÷ total runs | `fallback_rate`, `degraded_generation_rate` |
| 9 | **Retrieval quality** | Mean `retrieval_recall_at_5` on the golden set | evaluation harness |

---

## 2. Service Level Objectives

SLOs are set per detail level because a single latency target across a 100x
range of work is meaningless.

| SLO | Target | Window | Error budget |
|---|---|---|---|
| Availability | ≥ 99.5% | 30 days | 3h 39m |
| Delivery success | ≥ 99.0% | 30 days | 7h 18m |
| Summary p95 latency | ≤ 8 s | 7 days | 5% of requests |
| Comprehensive p95 latency | ≤ 45 s | 7 days | 5% of requests |
| Full-deck p95 latency | ≤ 120 s | 7 days | 5% of requests |
| Generation integrity | ≥ 99.9% clean | 30 days | 0.1% of runs |
| Groundedness | ≥ 0.85 mean | 7 days | — |
| Degradation rate | ≤ 5% | 7 days | — |

**Why these numbers.** Summary is an interactive action, so it is bounded by
human attention span. Full-deck is an explicitly batch-shaped operation and is
bounded by the proxy timeout the async path exists to avoid. Integrity is the
strictest objective because a single leaked identifier is a reportable event,
not a latency blip.

### Error budget policy

| Budget consumed | Action |
|---|---|
| < 50% | Normal feature delivery |
| 50–90% | Reliability work prioritised over new features |
| > 90% | Feature freeze; only reliability and quality fixes merge |
| Exhausted | Incident review, thresholds re-evaluated, ADR if the design is at fault |

---

## 3. Instrumentation already in place

| Signal | Mechanism | Where |
|---|---|---|
| Structured request logs | JSON log line per request with `request_id`, method, path, status, duration, user | `request_logging_middleware` |
| Request correlation | `X-Request-Id` accepted from the client or generated, echoed on every response | `request_logging_middleware` |
| Per-run KPI record | 50+ field `RunMetrics` appended to `build/docsynth_metrics.jsonl` | `telemetry.MetricsRegistry` |
| Aggregate snapshot | `GET /metrics` (JSON) — bounded 500-run window | `telemetry.MetricsRegistry.snapshot` |
| Scrape endpoint | `GET /metrics?format=prometheus` with `text/plain; version=0.0.4` | `telemetry.MetricsRegistry.prometheus` |
| Liveness | `GET /healthz` — dependency-free by design | `main.healthz` |
| Readiness | `GET /readyz` — artifact store writability + optional LLM reachability, 503 when not ready | `main.readyz` |
| Build provenance | `GET /version` — version, commit, build time, model routing, limits | `main.version` |
| Rate limit signals | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After`, `rate_limited` log events | `ingress_guard_middleware` |
| Quality benchmark | `GET /benchmarks` — latest evaluation report with gate status | `main.benchmarks` |

### Probe design note

Liveness and readiness are deliberately different. `/healthz` checks nothing but
the process, because a failing LLM must never cause Kubernetes to restart a
healthy pod — that turns a dependency outage into a crash loop. `/readyz` checks
real dependencies and returns 503 so the pod leaves the load balancer rotation
while staying alive to recover.

---

## 4. Prometheus scrape configuration

Pods are annotated for discovery in
[deploy/k8s/orchestrator-deployment.yaml](../deploy/k8s/orchestrator-deployment.yaml):

```yaml
annotations:
  prometheus.io/scrape: "true"
  prometheus.io/path: "/metrics"
  prometheus.io/port: "8080"
```

Static scrape config:

```yaml
scrape_configs:
  - job_name: docsynth-orchestrator
    metrics_path: /metrics
    params:
      format: ["prometheus"]
    static_configs:
      - targets: ["orchestrator.doc-optimizer.svc:8080"]
```

---

## 5. Alerting rules

Alerts fire on **symptoms users feel**, not on causes. Cause-based alerts (high
CPU, cache miss rate) belong on dashboards.

```yaml
groups:
  - name: docsynth-slo
    rules:
      - alert: DocSynthHighFailureRate
        expr: docsynth_success_rate < 0.99
        for: 10m
        labels: { severity: page }
        annotations:
          summary: "Compose success rate below SLO"
          runbook: docs/runbook-kubernetes.md

      - alert: DocSynthContentLeakDetected
        expr: increase(docsynth_leak_total[15m]) > 0
        for: 0m
        labels: { severity: page }
        annotations:
          summary: "Generated output contained leaked content"
          description: "Integrity is a zero-budget objective. Investigate immediately."

      - alert: DocSynthGroundednessDegraded
        expr: docsynth_groundedness_score < 0.85
        for: 30m
        labels: { severity: ticket }
        annotations:
          summary: "Groundedness below quality floor"
          description: "Check retrieval top scores before suspecting the model."

      - alert: DocSynthFallbackRateHigh
        expr: docsynth_fallback_rate > 0.05
        for: 15m
        labels: { severity: ticket }
        annotations:
          summary: "Excess traffic served by the deterministic fallback"
          description: "Usually inference tier saturation or a missing model."

      - alert: DocSynthLatencyBudgetBurn
        expr: docsynth_latency_p95_ms > 120000
        for: 15m
        labels: { severity: ticket }
        annotations:
          summary: "p95 latency above the full-deck SLO"

      - alert: DocSynthNotReady
        expr: up{job="docsynth-orchestrator"} == 0
        for: 5m
        labels: { severity: page }
        annotations:
          summary: "Orchestrator replicas unreachable"
```

---

## 6. Dashboard layout

Four rows, ordered so the first screen answers "is it broken, and for whom?"

**Row 1 — Service health**
availability · success rate · requests/min · rate-limited requests · replica readiness

**Row 2 — Latency**
p50/p95/p99 split by detail level · stage breakdown (extraction, generation, render) · throughput in slides/sec

**Row 3 — Generation quality**
groundedness · hallucination rate · coverage · schema compliance · leak counts · fallback and degraded rates

**Row 4 — Retrieval and cost**
recall@5 · MRR · nDCG@10 · top score distribution · cache hit rate · tokens used · estimated cost per document

---

## 7. Failure analysis playbook

| Symptom | First check | Likely cause |
|---|---|---|
| Success rate drop | `fallback_rate` on `/metrics` | Inference tier down or model not pulled |
| Latency spike, quality stable | stage latency breakdown | Deck parsing or figure extraction, not the model |
| Quality drop, latency stable | `retrieval_top_score`, `grounding_sources` | Retrieval regression — check before blaming the model |
| Leak detected | `leak_counts` breakdown by type | Prompt or post-processing regression; reproduce with the golden `integrity` case |
| 429s rising | `rate_limited` log events by key | One caller saturating quota, or the limit is set below real demand |
| Pod restart loop | `kubectl describe pod` probe events | Liveness misconfiguration — liveness must never check dependencies |

---

## 8. Known gaps

Stated explicitly rather than implied by omission.

- **No distributed tracing.** Request IDs propagate but there is no span export.
  Accepted while the request path is a single service — see
  [ADR-0006](adr/0006-in-process-telemetry-over-otel-sdk.md).
- **Metrics are per replica.** Cross-replica aggregation is Prometheus's job;
  `/metrics` on one pod is not the fleet view.
- **Bounded window.** The in-memory snapshot covers the last 500 runs. Long-range
  analysis uses the JSONL log, not the endpoint.
- **Cost is estimated.** `cost_usd` is a modelled figure for self-hosted
  inference, useful for relative comparison, not for billing.
