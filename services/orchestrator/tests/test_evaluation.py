"""Tests for the generation-quality evaluation harness.

The eval harness is what blocks releases, so its scoring has to be correct. A
gate that silently passes is worse than no gate at all: these tests pin the
scorer, the aggregator, and the threshold comparison.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_MODULE_PATH = REPO_ROOT / "pipelines" / "eval" / "run_eval.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("docsynth_run_eval", EVAL_MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


run_eval = _load_eval_module()


# ---------------------------------------------------------------------------
# Golden dataset integrity
# ---------------------------------------------------------------------------


def test_golden_cases_are_well_formed_and_unique() -> None:
    cases = json.loads(run_eval.CASES_PATH.read_text(encoding="utf-8"))

    assert len(cases) >= 10, "the regression set must be broad enough to be meaningful"

    ids = [case["case_id"] for case in cases]
    assert len(ids) == len(set(ids)), "case ids must be unique"

    for case in cases:
        assert case.get("prompt"), f"{case['case_id']} has no prompt"
        assert case.get("source_text"), f"{case['case_id']} has no grounding source"
        assert case.get("category"), f"{case['case_id']} is uncategorised"


def test_golden_cases_cover_the_high_risk_categories() -> None:
    cases = json.loads(run_eval.CASES_PATH.read_text(encoding="utf-8"))
    categories = {case["category"] for case in cases}

    # These are the failure modes that matter for an enterprise GenAI product.
    assert {"hallucination_probe", "compliance", "grounding", "integrity"} <= categories


def test_thresholds_document_a_rationale_for_every_gate() -> None:
    thresholds = json.loads(run_eval.THRESHOLDS_PATH.read_text(encoding="utf-8"))

    assert thresholds["gates"], "at least one gate must be configured"
    for metric, rule in thresholds["gates"].items():
        assert rule.get("rationale"), f"gate {metric} must explain why the bound exists"
        assert ("min" in rule) or ("max" in rule), f"gate {metric} has no bound"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_coverage_counts_only_the_terms_present() -> None:
    case = {"must_include": ["alpha", "beta", "gamma", "delta"]}

    score = run_eval.score_output(case, "Alpha and BETA are present.")

    assert score["must_include_coverage"] == 0.5
    assert sorted(score["missing_terms"]) == ["delta", "gamma"]


def test_forbidden_terms_use_word_boundaries_to_avoid_false_positives() -> None:
    case = {"must_not_include": ["Slide"]}

    # "per-slide" is legitimate product vocabulary and must not trip the gate.
    clean = run_eval.score_output(case, "The per-slide extractor runs first.")
    leaked = run_eval.score_output(case, "See Slide 14 for the architecture.")

    assert clean["forbidden_term_clean"] is True
    assert leaked["forbidden_term_clean"] is False
    assert leaked["forbidden_terms_found"] == ["Slide"]


def test_pii_leakage_is_detected() -> None:
    case = {"must_not_include": ["jane.doe@contoso.com", "555-0142"]}

    score = run_eval.score_output(case, "Contact jane.doe@contoso.com for details.")

    assert score["forbidden_terms_found"] == ["jane.doe@contoso.com"]


def test_ordered_step_structure_is_enforced() -> None:
    case = {"requires_ordered_steps": True}

    assert run_eval.score_output(case, "1. Stop workers\n2. Drain queue")["structure_compliant"] is True
    assert run_eval.score_output(case, "Stop workers then drain the queue.")["structure_compliant"] is False


def test_table_structure_is_enforced() -> None:
    case = {"requires_table": True}
    table = "| Config | Throughput |\n| --- | --- |\n| Tuned | 42 |"

    assert run_eval.score_output(case, table)["structure_compliant"] is True
    assert run_eval.score_output(case, "Tuned throughput was 42.")["structure_compliant"] is False


def test_required_sections_are_enforced() -> None:
    case = {"required_sections": ["Summary", "Risks"]}

    assert run_eval.score_output(case, "## Summary\n## Risks\n")["structure_compliant"] is True
    assert run_eval.score_output(case, "## Summary\n")["structure_compliant"] is False


@pytest.mark.parametrize(
    ("case", "text", "expected"),
    [
        ({"max_words": 3}, "one two three", True),
        ({"max_words": 3}, "one two three four", False),
        ({"min_words": 4}, "one two three", False),
        ({"min_words": 2, "max_words": 4}, "one two three", True),
        ({}, "any length at all is fine here", True),
    ],
)
def test_length_compliance(case: dict, text: str, expected: bool) -> None:
    assert run_eval.score_output(case, text)["length_compliant"] is expected


def test_refusal_is_scored_only_when_expected() -> None:
    probe = {"expects_refusal": True}

    assert run_eval.score_output(probe, "The source does not contain that figure.")["refusal_correct"] is True
    assert run_eval.score_output(probe, "Q4 revenue was 12 million.")["refusal_correct"] is False
    # Cases that do not expect a refusal must not be scored on one at all.
    assert run_eval.score_output({}, "Anything")["refusal_correct"] is None


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


def _result(case_id: str, **overrides) -> dict:
    base = {
        "case_id": case_id,
        "ok": True,
        "latency_ms": 100,
        "must_include_coverage": 1.0,
        "forbidden_term_clean": True,
        "structure_compliant": True,
        "length_compliant": True,
        "refusal_correct": None,
        "word_count": 50,
    }
    base.update(overrides)
    return base


def test_summary_gates_only_on_the_selected_cases() -> None:
    results = [
        _result("gated", must_include_coverage=1.0),
        _result("advisory", must_include_coverage=0.0),
    ]

    summary = run_eval.summarise(results, gated_ids={"gated"})

    assert summary["gated_cases"] == 1
    assert summary["advisory_cases"] == 1
    assert summary["avg_must_include_coverage"] == 1.0


def test_worst_case_coverage_is_tracked_separately_from_the_average() -> None:
    results = [
        _result("a", must_include_coverage=1.0),
        _result("b", must_include_coverage=1.0),
        _result("c", must_include_coverage=0.2),
    ]

    summary = run_eval.summarise(results, gated_ids={"a", "b", "c"})

    assert summary["avg_must_include_coverage"] > 0.7
    assert summary["min_case_must_include_coverage"] == 0.2


def test_failed_cases_lower_the_pass_rate() -> None:
    results = [_result("a"), {"case_id": "b", "ok": False, "latency_ms": 5}]

    summary = run_eval.summarise(results, gated_ids={"a", "b"})

    assert summary["pass_rate"] == 0.5
    assert summary["passed_cases"] == 1


def test_leakage_rate_reflects_the_proportion_of_dirty_outputs() -> None:
    results = [_result("a"), _result("b", forbidden_term_clean=False)]

    summary = run_eval.summarise(results, gated_ids={"a", "b"})

    assert summary["forbidden_term_rate"] == 0.5


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------


def test_gate_fails_when_a_minimum_is_breached() -> None:
    thresholds = {"gates": {"avg_must_include_coverage": {"min": 0.9, "rationale": "x"}}}

    checks = run_eval.evaluate_gates({"avg_must_include_coverage": 0.5}, thresholds)

    assert checks[0]["status"] == "fail"


def test_gate_fails_when_a_maximum_is_breached() -> None:
    thresholds = {"gates": {"p95_latency_ms": {"max": 1000, "rationale": "x"}}}

    checks = run_eval.evaluate_gates({"p95_latency_ms": 5000}, thresholds)

    assert checks[0]["status"] == "fail"


def test_gate_is_skipped_rather_than_silently_passed_when_data_is_missing() -> None:
    thresholds = {"gates": {"refusal_accuracy": {"min": 1.0, "rationale": "x"}}}

    checks = run_eval.evaluate_gates({}, thresholds)

    assert checks[0]["status"] == "skipped"


def test_baseline_comparison_flags_quality_regressions() -> None:
    thresholds = {"regression_tolerance": {"avg_must_include_coverage": 0.03}}
    summary = {"avg_must_include_coverage": 0.80}
    baseline = {"summary": {"avg_must_include_coverage": 0.95}}

    deltas = run_eval.compare_baseline(summary, baseline, thresholds)

    assert deltas[0]["status"] == "regression"
    assert deltas[0]["delta"] == pytest.approx(-0.15)


def test_baseline_comparison_accepts_movement_inside_tolerance() -> None:
    thresholds = {"regression_tolerance": {"avg_must_include_coverage": 0.05}}
    summary = {"avg_must_include_coverage": 0.93}
    baseline = {"summary": {"avg_must_include_coverage": 0.95}}

    deltas = run_eval.compare_baseline(summary, baseline, thresholds)

    assert deltas[0]["status"] == "ok"


def test_latency_regression_is_measured_as_a_percentage() -> None:
    thresholds = {"regression_tolerance": {"p95_latency_ms_pct": 0.25}}
    baseline = {"summary": {"p95_latency_ms": 1000}}

    within = run_eval.compare_baseline({"p95_latency_ms": 1200}, baseline, thresholds)
    beyond = run_eval.compare_baseline({"p95_latency_ms": 2000}, baseline, thresholds)

    assert within[0]["status"] == "ok"
    assert beyond[0]["status"] == "regression"


# ---------------------------------------------------------------------------
# End-to-end harness run
# ---------------------------------------------------------------------------


def test_mock_mode_run_passes_the_committed_gates(tmp_path) -> None:
    """The deterministic floor must always clear the gate.

    If this fails, either the fallback composer regressed or a threshold was
    raised without the pipeline being able to meet it.
    """
    output = tmp_path / "report.json"

    exit_code = run_eval.main(["--mode", "mock", "--gate", "--output", str(output)])
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["gate_status"] == "pass"
    assert report["mode"] == "mock"
    assert report["case_count"] >= 10


def test_mock_mode_marks_generation_dependent_cases_as_advisory(tmp_path) -> None:
    output = tmp_path / "report.json"
    run_eval.main(["--mode", "mock", "--output", str(output)])
    report = json.loads(output.read_text(encoding="utf-8"))

    # Refusal and redaction behaviour cannot be proven without a real model, so
    # those cases are reported but excluded from the mock-mode gate.
    assert "adversarial-unanswerable" in report["advisory_case_ids"]
    assert "compliance-redaction" in report["advisory_case_ids"]
    assert set(report["gated_case_ids"]).isdisjoint(report["advisory_case_ids"])
