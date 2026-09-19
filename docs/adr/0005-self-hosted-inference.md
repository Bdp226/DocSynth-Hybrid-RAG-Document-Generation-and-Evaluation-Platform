# ADR-0005: Self-hosted inference instead of a managed LLM API

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** Product owner, Security owner, Platform owner

## Context

The input to this system is unreleased enterprise material: internal
architecture decks, incident notes, roadmaps, and customer records. The target
users are in organisations where sending that content to a third-party
inference provider requires a data-transfer review that takes longer than the
project itself.

A secondary factor is cost shape. Document synthesis is bursty and
token-expensive — a full-deck job emits six figures of characters. Per-token
pricing makes the marginal cost of a thorough document unpredictable, which
discourages exactly the usage the product is for.

## Decision

Run inference on a self-hosted Ollama tier inside the deployment boundary.
Outbound internet access is disabled by default. Model routing (fast / default /
strong / vision) is configuration, not code.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| Managed frontier API | Highest output quality, but data leaves the boundary. Blocked by the primary use case, not by preference. |
| Managed API with PII redaction first | Redaction is best-effort; a single missed identifier is a reportable incident. The residual risk is not worth the quality gain. |
| Hybrid routing — local for sensitive, managed for the rest | Requires a reliable sensitivity classifier. Misclassification is silent and unrecoverable. Deferred. |
| Fine-tuned small model | No labelled corpus yet, and it would couple the product to a training pipeline before the product is proven. |

## Consequences

**Positive**

- No enterprise content crosses the trust boundary; compliance review is about
  infrastructure, not data export.
- Cost is a fixed GPU node rather than an unpredictable per-token bill, so
  long-form generation is not rationed.
- Latency and availability are controlled locally, with no vendor rate limits.
- Prompts are cached on disk, which is only safe *because* inference is local.

**Negative / accepted cost**

- Output quality is below a frontier model. The evaluation gate exists partly to
  make that ceiling visible and measurable rather than assumed.
- Cold model loads are slow, which is why readiness uses a startup probe and
  liveness never checks the LLM (see ADR-0002 and the K8s manifest).
- Operating the inference tier — GPU nodes, model pulls, version drift — is now
  the team's problem.

## Revisit when

An approved managed provider exists inside the compliance boundary, or local
model quality plateaus below the thresholds in `pipelines/eval/thresholds.json`.
