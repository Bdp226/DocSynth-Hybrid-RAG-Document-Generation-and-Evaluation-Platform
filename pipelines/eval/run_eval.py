from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import httpx


def _mock_case_result(case: dict, latency_ms: int) -> dict:
    draft = f"Summary\nRisk\nMitigation\n{case.get('source_text', '')}"
    must_include = case.get("must_include", [])
    hits = sum(1 for term in must_include if term.lower() in draft.lower())
    coverage = (hits / len(must_include)) if must_include else 1.0

    return {
        "case_id": case["case_id"],
        "ok": True,
        "latency_ms": latency_ms,
        "must_include_coverage": round(coverage, 3),
        "artifact_count": 1,
        "retrieval_latency_ms": 0,
        "grounded_source_count": 0,
        "retrieved_chunks": 0,
        "cache_hits": 0,
        "mode": "mock",
    }


def evaluate_case(api_base: str, case: dict, headers: dict[str, str], use_mock: bool) -> dict:
    start = time.perf_counter()
    payload = {
        "document_id": case["case_id"],
        "user_prompt": case["prompt"],
        "source_text": case.get("source_text", ""),
        "instructions": case.get("instructions", []),
        "objective": "Evaluate output quality",
        "domain": "evaluation",
        "output_formats": ["docx"],
        "include_inline_artifacts": False,
        "image_inputs": [],
    }

    latency_ms = int((time.perf_counter() - start) * 1000)

    if use_mock:
        return _mock_case_result(case, latency_ms)

    response = httpx.post(f"{api_base}/compose", json=payload, headers=headers, timeout=120)

    if response.status_code != 200:
        return {
            "case_id": case["case_id"],
            "ok": False,
            "latency_ms": latency_ms,
            "error": response.text,
        }

    data = response.json()
    text = data.get("optimized_text", "")
    must_include = case.get("must_include", [])
    hits = sum(1 for term in must_include if term.lower() in text.lower())
    coverage = (hits / len(must_include)) if must_include else 1.0

    return {
        "case_id": case["case_id"],
        "ok": True,
        "latency_ms": latency_ms,
        "must_include_coverage": round(coverage, 3),
        "artifact_count": len(data.get("artifacts", [])),
        "retrieval_latency_ms": int(data.get("retrieval_stats", {}).get("retrieval_latency_ms", 0)),
        "grounded_source_count": len(data.get("workspace_sources", [])),
        "retrieved_chunks": int(data.get("retrieval_stats", {}).get("returned_chunks", 0)),
        "cache_hits": int(data.get("retrieval_stats", {}).get("cache_hits", 0)),
    }


def main() -> None:
    api_base = "http://localhost:8080"
    use_mock = os.getenv("EVAL_MOCK", "false").lower() == "true"
    headers = {
        "X-User-Id": "eval-runner",
        "X-User-Role": "author",
    }

    cases = json.loads(Path("pipelines/eval/sample_cases.json").read_text(encoding="utf-8"))
    results = [evaluate_case(api_base, case, headers, use_mock=use_mock) for case in cases]

    ok_results = [r for r in results if r.get("ok")]
    latencies = [r["latency_ms"] for r in ok_results]

    summary = {
        "total_cases": len(results),
        "passed_cases": len(ok_results),
        "pass_rate": round((len(ok_results) / len(results)) if results else 0.0, 3),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "p95_latency_ms": sorted(latencies)[max(int(len(latencies) * 0.95) - 1, 0)] if latencies else None,
        "avg_must_include_coverage": round(statistics.mean([r["must_include_coverage"] for r in ok_results]), 3)
        if ok_results
        else None,
        "avg_retrieval_latency_ms": round(statistics.mean([r.get("retrieval_latency_ms", 0) for r in ok_results]), 2)
        if ok_results
        else None,
        "avg_grounded_source_count": round(statistics.mean([r.get("grounded_source_count", 0) for r in ok_results]), 2)
        if ok_results
        else None,
        "avg_retrieved_chunks": round(statistics.mean([r.get("retrieved_chunks", 0) for r in ok_results]), 2)
        if ok_results
        else None,
        "avg_cache_hits": round(statistics.mean([r.get("cache_hits", 0) for r in ok_results]), 2)
        if ok_results
        else None,
    }

    output = {
        "mode": "mock" if use_mock else "live",
        "summary": summary,
        "results": results,
    }

    out_path = Path("pipelines/eval/last_eval_report.json")
    out_path.write_text(json.dumps(output, indent=2), encoding="utf-8")

    print(json.dumps(output, indent=2))
    print(f"Wrote report to {out_path}")


if __name__ == "__main__":
    main()
