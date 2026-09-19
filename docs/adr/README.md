# Architecture Decision Records

An ADR captures **why** a structural decision was made, what was rejected, and
what it costs. Code shows what the system does; these explain what it refuses to
do and why.

## Index

| ID | Decision | Status |
|---|---|---|
| [0001](0001-hybrid-retrieval-over-pure-vector-search.md) | Hybrid BM25 + embedding retrieval over pure vector search | Accepted |
| [0002](0002-deterministic-fallback-over-hard-failure.md) | Deterministic fallback composer instead of hard failure | Accepted |
| [0003](0003-rule-based-evaluation-over-llm-judge.md) | Rule-based evaluation gate instead of an LLM judge | Accepted |
| [0004](0004-in-process-rate-limiting.md) | In-process rate limiting as a per-replica backstop | Accepted |
| [0005](0005-self-hosted-inference.md) | Self-hosted inference instead of a managed LLM API | Accepted |
| [0006](0006-in-process-telemetry-over-otel-sdk.md) | In-process telemetry registry instead of the OpenTelemetry SDK | Accepted |
| [0007](0007-synchronous-and-async-compose-paths.md) | Offering both synchronous and asynchronous compose paths | Accepted |

## Writing a new ADR

Copy [template.md](template.md), take the next number, and keep it to one page.
An ADR that cannot be read in two minutes will not be read.

Statuses: `Proposed` → `Accepted` → `Superseded by ADR-NNNN` / `Deprecated`.
Never delete an ADR. Superseding one is the historical record.
