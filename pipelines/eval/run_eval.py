"""DocSynth generation-quality evaluation harness.

This is the quality gate for the project. Unit tests prove the code runs; this
harness proves the *output* is still good enough to ship.

Design notes
------------
* **Deterministic scoring.** Every metric is computed from the generated text
  with rules, not with another LLM. An LLM judge is non-reproducible and cannot
  block a build credibly.
* **Per-case scoring, aggregate gating.** Each case yields independent coverage,
  leakage, structure, and length scores. The gate then asserts both the average
  and the worst case, so a single catastrophic failure cannot hide behind a good
  mean.
* **Mode awareness.** Cases flagged ``requires_generation`` depend on a real
  model (refusal behaviour, redaction, table synthesis). In ``mock`` mode they
  are scored and reported but excluded from the pass/fail gate, and the report
  says so explicitly. This keeps CI honest rather than green-by-construction.

Usage
-----
    python pipelines/eval/run_eval.py                  # live, against localhost:8080
    python pipelines/eval/run_eval.py --mode mock      # no service required
    python pipelines/eval/run_eval.py --gate           # exit 1 on KPI violation
    python pipelines/eval/run_eval.py --baseline       # diff against committed report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = REPO_ROOT / "pipelines" / "eval"
CASES_PATH = EVAL_DIR / "sample_cases.json"
THRESHOLDS_PATH = EVAL_DIR / "thresholds.json"
REPORT_PATH = EVAL_DIR / "last_eval_report.json"

ORDERED_STEP_PATTERN = re.compile(r"^\s*(?:\d+[.)]|step\s+\d+)", re.IGNORECASE | re.MULTILINE)
TABLE_PATTERN = re.compile(r"^\s*\|.*\|\s*$", re.MULTILINE)
REFUSAL_MARKERS = (
    "not contain",
    "no financial information",
    "does not include",
    "not available in the source",
    "cannot be determined",
    "not stated in the source",
)


def _contains_term(text: str, term: str) -> bool:
    """Boundary-aware containment check for forbidden terms.

    Naive substring matching produces false positives that make the leakage gate
    untrustworthy: banning "Slide" would flag the legitimate word "per-slide".
    Hyphens are treated as boundaries so compound words are not split open.
    """
    pattern = rf"(?<![\w-]){re.escape(term)}(?![\w-])"
    return re.search(pattern, text, re.IGNORECASE) is not None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_output(case: dict[str, Any], text: str) -> dict[str, Any]:
    """Score one generated document against its labelled expectations."""
    haystack = text.lower()
    words = len(text.split())

    must_include = case.get("must_include", [])
    # Coverage uses substring matching on purpose: "Risk" should credit "risks".
    hits = [term for term in must_include if term.lower() in haystack]
    coverage = (len(hits) / len(must_include)) if must_include else 1.0

    must_not_include = case.get("must_not_include", [])
    leaked = [term for term in must_not_include if _contains_term(text, term)]

    structure_checks: list[bool] = []
    if case.get("requires_ordered_steps"):
        structure_checks.append(bool(ORDERED_STEP_PATTERN.search(text)))
    if case.get("requires_table"):
        structure_checks.append(bool(TABLE_PATTERN.search(text)))
    for section in case.get("required_sections", []):
        structure_checks.append(section.lower() in haystack)
    structure_ok = all(structure_checks) if structure_checks else True

    max_words = case.get("max_words")
    min_words = case.get("min_words")
    length_ok = True
    if isinstance(max_words, int) and words > max_words:
        length_ok = False
    if isinstance(min_words, int) and words < min_words:
        length_ok = False

    refusal_ok: bool | None = None
    if case.get("expects_refusal"):
        refusal_ok = any(marker in haystack for marker in REFUSAL_MARKERS)

    return {
        "must_include_coverage": round(coverage, 3),
        "missing_terms": [term for term in must_include if term not in hits],
        "forbidden_terms_found": leaked,
        "forbidden_term_clean": not leaked,
        "structure_compliant": structure_ok,
        "structure_checks_run": len(structure_checks),
        "length_compliant": length_ok,
        "word_count": words,
        "refusal_correct": refusal_ok,
    }


# ---------------------------------------------------------------------------
# Execution modes
# ---------------------------------------------------------------------------


def _deterministic_draft(case: dict[str, Any]) -> str:
    """Reproduce the service's deterministic floor without a model.

    Mirrors the structure-preserving fallback the orchestrator uses when the LLM
    is unavailable: a titled document that restates the grounded source. It sets
    the lower bound on quality — the model must beat this, never fall below it.
    """
    source = case.get("source_text", "")
    instructions = case.get("instructions", [])
    body = "\n".join(f"- {line.strip()}" for line in source.split(". ") if line.strip())

    sections = [
        f"# {case.get('prompt', 'Generated Document').rstrip('.')}",
        "",
        "## Summary",
        source,
        "",
        "## Key Points",
        body,
    ]
    if instructions:
        sections += ["", "## Applied Instructions", *[f"- {item}" for item in instructions]]
    return "\n".join(sections)


def run_case_mock(case: dict[str, Any]) -> dict[str, Any]:
    start = time.perf_counter()
    text = _deterministic_draft(case)
    latency_ms = int((time.perf_counter() - start) * 1000)

    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "category": case.get("category", "uncategorised"),
        "difficulty": case.get("difficulty", "unknown"),
        "requires_generation": bool(case.get("requires_generation")),
        "ok": True,
        "mode": "mock",
        "latency_ms": latency_ms,
        "artifact_count": 1,
        "retrieval_latency_ms": 0,
        "grounded_source_count": 0,
        "retrieved_chunks": 0,
        "cache_hits": 0,
        "policy_flags": [],
    }
    result.update(score_output(case, text))
    return result


def run_case_live(api_base: str, case: dict[str, Any], headers: dict[str, str], timeout: float) -> dict[str, Any]:
    payload = {
        "document_id": case["case_id"],
        "user_prompt": case["prompt"],
        "source_text": case.get("source_text", ""),
        "instructions": case.get("instructions", []),
        "objective": "Evaluate output quality against the golden regression set",
        "domain": "evaluation",
        "output_formats": ["docx"],
        "include_inline_artifacts": False,
        "image_inputs": [],
    }

    start = time.perf_counter()
    try:
        response = httpx.post(f"{api_base}/compose", json=payload, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        return {
            "case_id": case["case_id"],
            "category": case.get("category", "uncategorised"),
            "requires_generation": bool(case.get("requires_generation")),
            "ok": False,
            "mode": "live",
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "error": f"transport_error: {exc}",
        }
    latency_ms = int((time.perf_counter() - start) * 1000)

    if response.status_code != 200:
        return {
            "case_id": case["case_id"],
            "category": case.get("category", "uncategorised"),
            "requires_generation": bool(case.get("requires_generation")),
            "ok": False,
            "mode": "live",
            "latency_ms": latency_ms,
            "error": f"http_{response.status_code}: {response.text[:500]}",
        }

    data = response.json()
    retrieval = data.get("retrieval_stats", {}) or {}

    result: dict[str, Any] = {
        "case_id": case["case_id"],
        "category": case.get("category", "uncategorised"),
        "difficulty": case.get("difficulty", "unknown"),
        "requires_generation": bool(case.get("requires_generation")),
        "ok": True,
        "mode": "live",
        "latency_ms": latency_ms,
        "artifact_count": len(data.get("artifacts", [])),
        "retrieval_latency_ms": int(retrieval.get("retrieval_latency_ms", 0)),
        "retrieval_top_score": retrieval.get("top_score"),
        "grounded_source_count": len(data.get("workspace_sources", [])),
        "retrieved_chunks": int(retrieval.get("returned_chunks", 0)),
        "cache_hits": int(retrieval.get("cache_hits", 0)),
        "policy_flags": data.get("policy_flags", []),
        "model_used": data.get("model_used"),
    }
    result.update(score_output(case, data.get("optimized_text", "")))

    if case.get("expects_policy_flags"):
        result["policy_detection_correct"] = bool(result["policy_flags"])

    return result


# ---------------------------------------------------------------------------
# Aggregation and gating
# ---------------------------------------------------------------------------


def _percentile(values: list[int], pct: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(int(len(ordered) * pct) - 1, 0)
    return ordered[index]


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def summarise(results: list[dict[str, Any]], gated_ids: set[str]) -> dict[str, Any]:
    """Aggregate per-case scores, gating only on the cases valid for this mode."""
    ok = [r for r in results if r.get("ok")]
    gated = [r for r in ok if r["case_id"] in gated_ids]
    latencies = [r["latency_ms"] for r in ok]

    coverages = [r["must_include_coverage"] for r in gated if "must_include_coverage" in r]
    clean = [r for r in gated if r.get("forbidden_term_clean") is not None]
    structure = [r for r in gated if r.get("structure_compliant") is not None]
    lengths = [r for r in gated if r.get("length_compliant") is not None]
    refusals = [r for r in gated if r.get("refusal_correct") is not None]

    return {
        "total_cases": len(results),
        "passed_cases": len(ok),
        "gated_cases": len(gated),
        "advisory_cases": len(ok) - len(gated),
        "pass_rate": round(len(ok) / len(results), 3) if results else 0.0,
        "avg_must_include_coverage": _mean(coverages),
        "min_case_must_include_coverage": round(min(coverages), 3) if coverages else None,
        "forbidden_term_rate": round(sum(0 if r["forbidden_term_clean"] else 1 for r in clean) / len(clean), 3)
        if clean
        else 0.0,
        "structure_compliance_rate": round(sum(1 for r in structure if r["structure_compliant"]) / len(structure), 3)
        if structure
        else 1.0,
        "length_compliance_rate": round(sum(1 for r in lengths if r["length_compliant"]) / len(lengths), 3)
        if lengths
        else 1.0,
        "refusal_accuracy": round(sum(1 for r in refusals if r["refusal_correct"]) / len(refusals), 3)
        if refusals
        else 1.0,
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "avg_word_count": _mean([float(r["word_count"]) for r in ok if "word_count" in r]),
        "avg_retrieval_latency_ms": _mean([float(r.get("retrieval_latency_ms", 0)) for r in ok]),
        "avg_grounded_source_count": _mean([float(r.get("grounded_source_count", 0)) for r in ok]),
        "avg_retrieved_chunks": _mean([float(r.get("retrieved_chunks", 0)) for r in ok]),
        "avg_cache_hits": _mean([float(r.get("cache_hits", 0)) for r in ok]),
    }


def evaluate_gates(summary: dict[str, Any], thresholds: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare the summary against configured thresholds.

    Returns one record per gate so the report shows every check, not only the
    failures. Silent gates are how quality standards quietly erode.
    """
    checks: list[dict[str, Any]] = []

    for metric, rule in thresholds.get("gates", {}).items():
        actual = summary.get(metric)
        if actual is None:
            checks.append({"metric": metric, "status": "skipped", "reason": "metric not produced by this run"})
            continue

        floor = rule.get("min")
        ceiling = rule.get("max")
        passed = True
        if floor is not None and actual < floor:
            passed = False
        if ceiling is not None and actual > ceiling:
            passed = False

        checks.append(
            {
                "metric": metric,
                "status": "pass" if passed else "fail",
                "actual": actual,
                "min": floor,
                "max": ceiling,
                "rationale": rule.get("rationale", ""),
            }
        )

    return checks


def compare_baseline(
    summary: dict[str, Any], baseline: dict[str, Any], thresholds: dict[str, Any]
) -> list[dict[str, Any]]:
    """Report per-KPI movement versus the committed report."""
    tolerance = thresholds.get("regression_tolerance", {})
    baseline_summary = baseline.get("summary", {})
    deltas: list[dict[str, Any]] = []

    for metric, allowed_drop in tolerance.items():
        if metric.startswith("_"):
            continue

        if metric.endswith("_pct"):
            # Percentage tolerances describe "how much worse is acceptable",
            # e.g. p95_latency_ms_pct guards p95_latency_ms.
            key = metric.replace("_pct", "")
            current, previous = summary.get(key), baseline_summary.get(key)
            if current is None or previous in (None, 0):
                continue
            change = (current - previous) / previous
            deltas.append(
                {
                    "metric": key,
                    "baseline": previous,
                    "current": current,
                    "change_pct": round(change * 100, 2),
                    "status": "regression" if change > allowed_drop else "ok",
                }
            )
            continue

        current, previous = summary.get(metric), baseline_summary.get(metric)
        if current is None or previous is None:
            continue
        deltas.append(
            {
                "metric": metric,
                "baseline": previous,
                "current": current,
                "delta": round(current - previous, 4),
                "status": "regression" if (previous - current) > allowed_drop else "ok",
            }
        )

    return deltas


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    default_mode = os.getenv("EVAL_MODE") or ("mock" if os.getenv("EVAL_MOCK", "").lower() == "true" else "live")
    parser = argparse.ArgumentParser(description="Run the DocSynth generation-quality evaluation.")
    parser.add_argument(
        "--mode",
        choices=["live", "mock"],
        default=default_mode,
        help="live hits a running orchestrator; mock scores the deterministic floor with no service.",
    )
    parser.add_argument("--api-base", default=os.getenv("EVAL_API_BASE", "http://localhost:8080"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("EVAL_TIMEOUT", "180")))
    parser.add_argument("--gate", action="store_true", help="Exit non-zero when any quality gate fails.")
    parser.add_argument("--baseline", action="store_true", help="Compare this run against the committed report.")
    parser.add_argument(
        "--baseline-path",
        type=Path,
        default=REPORT_PATH,
        help="Committed report used as the regression baseline.",
    )
    parser.add_argument("--output", type=Path, default=REPORT_PATH)
    parser.add_argument("--no-write", action="store_true", help="Score without overwriting the report file.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    cases: list[dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    thresholds: dict[str, Any] = json.loads(THRESHOLDS_PATH.read_text(encoding="utf-8"))

    previous: dict[str, Any] = {}
    if args.baseline and args.baseline_path.exists():
        # Always compare against the committed report, even when this run writes
        # somewhere else (CI writes to a temp path so it never mutates the repo).
        previous = json.loads(args.baseline_path.read_text(encoding="utf-8"))

    headers = {"X-User-Id": "eval-runner", "X-User-Role": "author"}

    if args.mode == "mock":
        results = [run_case_mock(case) for case in cases]
        gated_ids = {case["case_id"] for case in cases if not case.get("requires_generation")}
    else:
        results = [run_case_live(args.api_base, case, headers, args.timeout) for case in cases]
        gated_ids = {case["case_id"] for case in cases}

    summary = summarise(results, gated_ids)
    gate_checks = evaluate_gates(summary, thresholds)
    failures = [check for check in gate_checks if check["status"] == "fail"]

    report: dict[str, Any] = {
        "mode": args.mode,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "threshold_version": thresholds.get("version"),
        "case_count": len(cases),
        "gated_case_ids": sorted(gated_ids),
        "advisory_case_ids": sorted({c["case_id"] for c in cases} - gated_ids),
        "summary": summary,
        "gate_checks": gate_checks,
        "gate_status": "fail" if failures else "pass",
        "results": results,
    }

    if args.baseline and previous:
        report["baseline_comparison"] = compare_baseline(summary, previous, thresholds)

    if not args.no_write:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    _print_console_report(report)

    regressions = [d for d in report.get("baseline_comparison", []) if d["status"] == "regression"]
    if args.gate and (failures or regressions):
        return 1
    return 0


def _print_console_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print("\n" + "=" * 78)
    print(f"DocSynth quality evaluation - mode={report['mode']} cases={report['case_count']}")
    print("=" * 78)

    for label, key in (
        ("pass rate", "pass_rate"),
        ("avg must-include coverage", "avg_must_include_coverage"),
        ("worst-case coverage", "min_case_must_include_coverage"),
        ("forbidden term rate", "forbidden_term_rate"),
        ("structure compliance", "structure_compliance_rate"),
        ("length compliance", "length_compliance_rate"),
        ("refusal accuracy", "refusal_accuracy"),
        ("p95 latency (ms)", "p95_latency_ms"),
    ):
        print(f"  {label:<32}{summary.get(key)}")

    print("\nGate checks")
    print("-" * 78)
    for check in report["gate_checks"]:
        marker = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[check["status"]]
        print(
            f"  [{marker}] {check['metric']:<32} actual={check.get('actual')} "
            f"min={check.get('min')} max={check.get('max')}"
        )

    if report.get("baseline_comparison"):
        print("\nBaseline comparison")
        print("-" * 78)
        for delta in report["baseline_comparison"]:
            print(f"  [{delta['status'].upper():<10}] {delta['metric']:<32} {delta['baseline']} -> {delta['current']}")

    if report["advisory_case_ids"]:
        print("\nAdvisory only (scored, not gated in this mode):")
        for case_id in report["advisory_case_ids"]:
            print(f"  - {case_id}")

    print(f"\nOverall: {report['gate_status'].upper()}\n")


if __name__ == "__main__":
    sys.exit(main())
