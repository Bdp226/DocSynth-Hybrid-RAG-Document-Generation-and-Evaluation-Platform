# Evaluation Framework

How DocSynth decides whether its own output is good enough to ship.

> **Principle.** Unit tests prove the code runs. This framework proves the
> *output* is still correct. A release is blocked by either one.

---

## 1. Why a gate and not a dashboard

A quality dashboard tells you about a regression after it has shipped. A gate
prevents it. The cost of a gate is that it must be **reproducible**,
**attributable**, and **honest about its own limits** — otherwise engineers
learn to re-run it until it turns green, and it stops meaning anything.

That requirement rules out an LLM judge. The full reasoning is in
[ADR-0003](adr/0003-rule-based-evaluation-over-llm-judge.md).

---

## 2. The golden regression set

[pipelines/eval/sample_cases.json](../pipelines/eval/sample_cases.json) — 12
hand-labelled cases chosen to cover the ways this specific product fails, not to
maximise case count.

| Category | Case | What it defends against |
|---|---|---|
| `executive_summary` | `exec-summary-basic` | Dropping requested sections under compression |
| `status_report` | `status-report-concise` | Losing concrete figures during summarisation |
| `procedure` | `procedure-runbook` | Collapsing ordered steps into prose |
| `risk_register` | `risk-register` | Losing the severity/owner/mitigation triple |
| `synthesis` | `multi-source-synthesis` | Favouring one input and ignoring the others |
| `compliance` | `compliance-redaction` | Reproducing PII from the source |
| `grounding` | `grounding-strict` | Inventing metrics that were never measured |
| `hallucination_probe` | `adversarial-unanswerable` | Confidently answering an unanswerable question |
| `structure` | `table-extraction` | Ignoring an explicit table instruction |
| `long_form` | `long-form-dossier` | Thinning out coverage across long outputs |
| `instruction_following` | `instruction-following-limits` | Runaway length |
| `integrity` | `leakage-clean-output` | Leaking slide numbers and meeting chatter |

Each case carries labelled expectations:

```jsonc
{
  "case_id": "procedure-runbook",
  "category": "procedure",
  "difficulty": "medium",
  "prompt": "...",
  "source_text": "...",          // the grounding truth
  "instructions": ["..."],
  "must_include": ["drain", "snapshot"],        // required facts
  "must_not_include": ["Slide", "As an AI"],    // leakage probes
  "requires_ordered_steps": true,               // structural assertion
  "requires_table": false,
  "required_sections": [],
  "min_words": null,
  "max_words": 600,
  "expects_refusal": false,
  "expects_policy_flags": false,
  "requires_generation": true                   // advisory in mock mode
}
```

---

## 3. Metric definitions

Precise definitions matter more than the metric names.

| Metric | Definition | Matching rule |
|---|---|---|
| `must_include_coverage` | Required terms present ÷ required terms | **Substring**, case-insensitive. Deliberate: `"Risk"` should credit `"risks"`. |
| `min_case_must_include_coverage` | Lowest per-case coverage in the run | — |
| `forbidden_term_rate` | Cases containing any forbidden term ÷ cases | **Boundary-aware**, case-insensitive, hyphens count as boundaries. Naive substring matching would flag the legitimate word `per-slide` for a banned term `Slide`, which makes the leakage gate untrustworthy. |
| `structure_compliance_rate` | Cases satisfying every structural assertion ÷ cases with assertions | Ordered steps: `^\d+[.)]` or `step N`. Table: a markdown pipe row. Sections: heading text present. |
| `length_compliance_rate` | Cases within `[min_words, max_words]` ÷ cases with a bound | Whitespace-delimited word count |
| `refusal_accuracy` | Correct refusals ÷ cases expecting refusal | Match against an explicit refusal-marker vocabulary |
| `pass_rate` | Cases that executed without error ÷ total | Functional, not qualitative |
| `p95_latency_ms` | 95th percentile end-to-end case latency | — |

Aggregate **and** worst-case coverage are both gated, because an average alone
lets one catastrophic case hide behind eleven good ones.

---

## 4. Thresholds

[pipelines/eval/thresholds.json](../pipelines/eval/thresholds.json) — versioned
in git, every bound carrying a written rationale.

| Gate | Bound | Why |
|---|---|---|
| `pass_rate` | ≥ 1.0 | An errored case is a functional regression |
| `avg_must_include_coverage` | ≥ 0.85 | Below this, output drops facts the author explicitly required |
| `min_case_must_include_coverage` | ≥ 0.5 | Stops a single collapse hiding behind the mean |
| `forbidden_term_rate` | = 0.0 | PII and leakage are release blockers, not trade-offs |
| `structure_compliance_rate` | ≥ 0.9 | Structure is requested explicitly and breaks rendering downstream |
| `length_compliance_rate` | ≥ 0.9 | Runaway length is the most common silent failure |
| `refusal_accuracy` | = 1.0 | A confident fabrication is the worst failure mode |
| `p95_latency_ms` | ≤ 120000 | Aligned with the full-deck SLO |

Raising or lowering a bound is a reviewed change with a changelog entry. It
cannot be edited quietly.

---

## 5. Execution modes and honest scope

| Mode | What it runs against | Gated cases |
|---|---|---|
| `mock` | The deterministic floor — the same structure-preserving composer the service falls back to when the LLM is down | Cases **without** `requires_generation` |
| `live` | A running orchestrator with a real model | **All** cases |

Five cases — refusal behaviour, PII redaction, table synthesis, ordered-step
generation, chatter removal — genuinely cannot be proven without a model. In
`mock` mode they are **scored and reported but excluded from the pass/fail
decision**, and every report lists them under `advisory_case_ids`.

This is the most important property of the framework: **the gate never claims
more coverage than it actually has.** A gate that is green by construction is
worse than no gate.

The mock mode still has real value: it asserts that the deterministic fallback —
the quality floor the product guarantees when inference is unavailable — has not
regressed. The model must beat this floor, never fall below it.

---

## 6. Running it

```powershell
# Deterministic floor, no service required. This is what CI runs on every PR.
python pipelines/eval/run_eval.py --mode mock --gate

# Full gate against a running service with a real model.
python pipelines/eval/run_eval.py --mode live --gate --baseline

# Score without touching the committed report.
python pipelines/eval/run_eval.py --mode mock --no-write

# Or through the task runner
make eval-gate
```

Exit code `0` means every gate passed; `1` means at least one gate or baseline
regression failed.

---

## 7. Regression detection

`--baseline` diffs the run against the committed
[last_eval_report.json](../pipelines/eval/last_eval_report.json) using the
tolerances in `thresholds.json`:

```jsonc
"regression_tolerance": {
  "avg_must_include_coverage": 0.03,
  "structure_compliance_rate": 0.05,
  "length_compliance_rate": 0.05,
  "p95_latency_ms_pct": 0.25
}
```

Tolerances exist because absolute equality is noise-sensitive, but they are
tight enough that a real degradation cannot drift through unnoticed across
several PRs.

---

## 8. Reading a report

```
==============================================================================
DocSynth quality evaluation - mode=mock cases=12
==============================================================================
  pass rate                       1.0
  avg must-include coverage       1.0
  worst-case coverage             1.0
  forbidden term rate             0.0
  structure compliance            1.0
  length compliance               1.0
  refusal accuracy                1.0
  p95 latency (ms)                0

Gate checks
------------------------------------------------------------------------------
  [PASS] pass_rate                        actual=1.0 min=1.0 max=None
  [PASS] avg_must_include_coverage        actual=1.0 min=0.85 max=None
  [PASS] min_case_must_include_coverage   actual=1.0 min=0.5 max=None
  [PASS] forbidden_term_rate              actual=0.0 min=None max=0.0
  [PASS] structure_compliance_rate        actual=1.0 min=0.9 max=None
  [PASS] length_compliance_rate           actual=1.0 min=0.9 max=None
  [PASS] refusal_accuracy                 actual=1.0 min=1.0 max=None
  [PASS] p95_latency_ms                   actual=0 min=None max=120000

Advisory only (scored, not gated in this mode):
  - adversarial-unanswerable
  - compliance-redaction
  - leakage-clean-output
  - procedure-runbook
  - table-extraction

Overall: PASS
```

Every gate is printed, including the ones that passed. Showing only failures is
how quality standards quietly erode.

The same report is served at `GET /benchmarks` so the running service can state
the quality bar it was released against.

---

## 9. The harness is itself tested

[services/orchestrator/tests/test_evaluation.py](../services/orchestrator/tests/test_evaluation.py)
pins the scorer, the aggregator, and the threshold comparison — including the
boundary-matching rule and the advisory-case exclusion. A gate nobody tests is a
gate nobody should trust.

---

## 10. Extending the set

1. Add the case to `sample_cases.json` with a `category` and labelled
   expectations.
2. Set `requires_generation: true` if it cannot pass on the deterministic floor.
3. Run `python pipelines/eval/run_eval.py --mode mock` and confirm the case
   scores the way you intended before relying on it.
4. Commit the refreshed report so it becomes the new baseline.
5. Note the addition in [CHANGELOG.md](../CHANGELOG.md).

Add cases for **failures you have actually seen**. A regression set grown from
real incidents is worth far more than one grown from imagination.
