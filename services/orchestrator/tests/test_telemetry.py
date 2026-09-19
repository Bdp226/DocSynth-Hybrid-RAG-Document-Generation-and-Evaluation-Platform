from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.telemetry import (
    MetricsRegistry,
    RunMetrics,
    Stopwatch,
    analyze_document,
    compute_genai_quality_metrics,
    estimate_llm_authorship,
)


SAMPLE_DOCUMENT = """# Platform Reference — Technical Documentation

## Part 1: Solution Architecture

### Environment Provisioning

This section sets out the provisioning workflow for the sandbox environment.

[[IMAGE:slide_12_img1.png]]

| Component | Purpose |
| --- | --- |
| Gateway | Routes traffic |
| Store | Persists artefacts |

### Access Control

The platform enforces role based access across every tenant boundary.

## Part 2: Operations

### Step 1: Raise a request

Submit the onboarding request through the service portal.
"""


def test_analyze_document_extracts_structural_kpis():
    stats = analyze_document(SAMPLE_DOCUMENT)

    assert stats["parts"] == 2
    assert stats["procedure_steps"] == 1
    # Three '###' headings exist, one of which is a procedure step.
    assert stats["topics"] == 2
    assert stats["tables_rendered"] == 1
    assert stats["table_rows"] == 2
    assert stats["figures_embedded"] == 1
    assert stats["output_chars"] == len(SAMPLE_DOCUMENT)


def test_analyze_document_reports_clean_content_integrity():
    stats = analyze_document(SAMPLE_DOCUMENT)

    assert stats["leak_counts"] == {
        "slide_reference": 0,
        "roster_role": 0,
        "meeting_chatter": 0,
        "raw_bold_marker": 0,
    }
    assert stats["content_integrity_pass"] is True


def test_analyze_document_detects_leaked_artefacts():
    leaky = (
        "### Overview\n\n"
        "As shown on Slide 42, Ravi Kumar (PO) and Anita Rao (QA) agreed the plan.\n"
        "**Raw bold marker**\n"
        "Looping in the SCM team for the next review.\n"
    )

    stats = analyze_document(leaky)

    assert stats["leak_counts"]["slide_reference"] >= 1
    assert stats["leak_counts"]["roster_role"] >= 1
    assert stats["leak_counts"]["meeting_chatter"] >= 1
    assert stats["leak_counts"]["raw_bold_marker"] >= 1
    assert stats["content_integrity_pass"] is False


def test_image_tokens_are_not_counted_as_slide_leaks():
    # Internal placeholders carry slide numbers but never reach the rendered page.
    text = "### Topic\n\n[[IMAGE:slide_81_img2.png]]\n\nNarrative body text.\n"

    stats = analyze_document(text)

    assert stats["figures_embedded"] == 1
    assert stats["leak_counts"]["slide_reference"] == 0


def test_estimate_llm_authorship_counts_deterministic_openers():
    text = (
        "This section sets out the scope.\n"
        "The following material covers the workflow.\n"
        "A fully model authored narrative paragraph.\n"
    )

    llm_topics, coverage = estimate_llm_authorship(text, topics=3)

    assert llm_topics == 1
    assert coverage == round(1 / 3, 4)


def test_estimate_llm_authorship_is_safe_when_no_topics():
    assert estimate_llm_authorship("anything", topics=0) == (0, 0.0)


def test_registry_snapshot_is_empty_before_any_run():
    snapshot = MetricsRegistry().snapshot()

    assert snapshot["runs_observed"] == 0
    assert snapshot["latency_ms"] == {}


def _run(**overrides) -> RunMetrics:
    defaults = dict(
        document_id="doc",
        generation_mode="full_deck",
        succeeded=True,
        total_latency_ms=1000.0,
        topics=10,
        llm_topics=5,
        llm_coverage_rate=0.5,
        leak_counts={"slide_reference": 0},
        content_integrity_pass=True,
    )
    defaults.update(overrides)
    return RunMetrics(**defaults)


def test_registry_aggregates_latency_percentiles_and_quality():
    registry = MetricsRegistry()
    for latency in (100.0, 200.0, 300.0, 400.0):
        registry.record(_run(total_latency_ms=latency))

    snapshot = registry.snapshot()

    assert snapshot["runs_observed"] == 4
    assert snapshot["availability"]["success_rate"] == 1.0
    assert snapshot["latency_ms"]["p50"] <= snapshot["latency_ms"]["p95"]
    assert snapshot["latency_ms"]["max"] == 400.0
    assert snapshot["generation_quality"]["avg_llm_coverage_rate"] == 0.5
    assert snapshot["content_integrity"]["clean_document_rate"] == 1.0


def test_registry_tracks_genai_quality_metrics():
    registry = MetricsRegistry()
    registry.record(
        _run(
            groundedness_score=0.96,
            hallucination_rate=0.02,
            retrieval_recall_at_5=0.95,
            retrieval_recall_at_10=0.97,
            mrr=0.93,
            ndcg_at_10=0.94,
            coverage_score=0.91,
            leakage_rate=0.0,
            schema_compliance_rate=0.98,
            cost_usd=0.015,
            tokens_used=2400,
            model_used="llama3.1:8b-instruct",
            model_route="full_deck",
        )
    )

    snapshot = registry.snapshot()

    assert snapshot["generation_quality"]["avg_groundedness_score"] == 0.96
    assert snapshot["generation_quality"]["avg_hallucination_rate"] == 0.02
    assert snapshot["generation_quality"]["avg_retrieval_recall_at_5"] == 0.95
    assert snapshot["generation_quality"]["avg_model_cost_usd"] == 0.015
    assert snapshot["generation_quality"]["avg_tokens_used"] == 2400


def test_registry_flags_degraded_generation_when_model_not_used():
    registry = MetricsRegistry()
    registry.record(_run(llm_topics=0, llm_coverage_rate=0.0))
    registry.record(_run())

    snapshot = registry.snapshot()

    assert snapshot["availability"]["degraded_generation_rate"] == 0.5


def test_registry_records_failures_in_availability():
    registry = MetricsRegistry()
    registry.record(_run())
    registry.record(_run(succeeded=False))

    snapshot = registry.snapshot()

    assert snapshot["availability"]["success_rate"] == 0.5
    assert snapshot["availability"]["documents_delivered"] == 1


def test_registry_writes_jsonl_log(tmp_path):
    log_path = tmp_path / "nested" / "kpi.jsonl"
    registry = MetricsRegistry(log_path=log_path)

    registry.record(_run())

    assert log_path.exists()
    assert '"document_id": "doc"' in log_path.read_text(encoding="utf-8")


def test_compute_genai_quality_metrics_returns_real_values():
    metrics = compute_genai_quality_metrics(
        output_chars=4200,
        topics=12,
        llm_topics=9,
        llm_coverage_rate=0.75,
        retrieval_top_score=0.81,
        leak_counts={"slide_reference": 0, "roster_role": 0, "meeting_chatter": 0, "raw_bold_marker": 0},
        content_integrity_pass=True,
    )

    assert metrics["groundedness_score"] > 0.0
    assert metrics["hallucination_rate"] < 1.0
    assert metrics["retrieval_recall_at_5"] > 0.0
    assert metrics["retrieval_recall_at_10"] > metrics["retrieval_recall_at_5"] * 0.5
    assert metrics["coverage_score"] > 0.5
    assert metrics["schema_compliance_rate"] == 1.0
    assert metrics["tokens_used"] > 0
    assert metrics["cost_usd"] > 0.0


def test_registry_never_raises_when_log_path_is_unwritable(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    registry = MetricsRegistry(log_path=blocker / "kpi.jsonl")

    # Telemetry must degrade silently rather than fail the request.
    registry.record(_run())

    assert registry.snapshot()["runs_observed"] == 1


def test_prometheus_exposition_contains_gauges():
    registry = MetricsRegistry()
    registry.record(_run())

    text = registry.prometheus()

    assert "docsynth_runs_observed 1" in text
    assert "docsynth_availability_success_rate" in text
    assert "# TYPE docsynth_latency_ms_p50 gauge" in text


def test_stopwatch_reports_monotonic_phases():
    stopwatch = Stopwatch()
    first = stopwatch.lap_ms()
    second = stopwatch.lap_ms()

    assert first >= 0.0
    assert second >= 0.0
    assert stopwatch.total_ms() >= first
