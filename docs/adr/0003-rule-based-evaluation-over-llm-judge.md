# ADR-0003: Rule-based evaluation gate instead of an LLM judge

- **Status:** Accepted
- **Date:** 2026-09-19
- **Deciders:** ML owner, Release owner

## Context

Output quality needed to become a build gate, not a subjective review comment.
The industry-default approach is an LLM-as-judge: ask a strong model to score
the generated document.

For a *blocking CI gate* this fails three tests:

1. **Reproducibility.** The same PR can pass and then fail with no code change.
   A non-deterministic gate trains engineers to re-run CI until it goes green,
   which destroys the gate's authority.
2. **Attribution.** "The judge scored 6/10" is not actionable. "Case
   `compliance-redaction` leaked `jane.doe@contoso.com`" is.
3. **Circularity.** Judging a local model's output with a model of comparable
   capability measures agreement, not correctness.

## Decision

Score every golden case with deterministic rules — required-term coverage,
boundary-aware forbidden-term detection, structural assertions (ordered steps,
tables, sections), and length compliance — and gate on aggregate thresholds
declared in `pipelines/eval/thresholds.json`.

## Alternatives considered

| Option | Why it was rejected |
|---|---|
| LLM-as-judge | Non-reproducible, non-attributable, and circular. Cannot credibly block a merge. |
| Human review only | Does not scale, does not run on every PR, and drifts as reviewers change. |
| Embedding similarity to a reference answer | Rewards paraphrase of a single "correct" document and punishes legitimate alternative structures. High similarity also tolerates confident factual errors. |
| No gate, dashboards only | Quality regressions get noticed weeks later, after they have shipped. |

## Consequences

**Positive**

- Identical input always yields an identical score; a red gate is always a real
  regression.
- Failures name the exact case and the exact term, so the fix is obvious.
- The gate runs with no GPU and no model, so it is free and fast on every PR.
- Thresholds are versioned in git: raising or lowering a bar is a reviewed
  change with a changelog entry, not a quiet edit.

**Negative / accepted cost**

- Rules measure *checkable* quality, not prose elegance. A fluent but clumsy
  document can pass.
- The golden set must be maintained by hand; stale cases give false confidence.
- Cases that genuinely need a model (refusal behaviour, PII redaction, table
  synthesis) are marked `requires_generation` and are **advisory** in mock mode.
  They are gated only in live mode. This is stated in every report so the gate
  never claims more coverage than it has.

## Revisit when

An LLM judge becomes viable as a *non-blocking* signal alongside the rules, or
the golden set grows past the point where manual curation is sustainable.
