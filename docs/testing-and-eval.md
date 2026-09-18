# Testing and Evaluation Guide

## Automated tests

Scope covered:
- Policy checks
- Artifact generation
- API flows for optimize/compose/download authorization

Run:

```powershell
cd services/orchestrator
..\..\.venv\Scripts\python -m pip install -r requirements-dev.txt
..\..\.venv\Scripts\python -m pytest tests -q
```

## Evaluation harness

The baseline harness runs sample compose cases and computes:
- Pass rate
- Average and p95 latency
- Must-include coverage

Run:

```powershell
cd ..\..
.\.venv\Scripts\python pipelines/eval/run_eval.py
```

If your private LLM endpoint is unavailable, run deterministic mock mode:

```powershell
$env:EVAL_MOCK="true"
.\.venv\Scripts\python pipelines/eval/run_eval.py
```

Inputs:
- `pipelines/eval/sample_cases.json`

Output:
- `pipelines/eval/last_eval_report.json`

## Notes

- The evaluation script expects API server on `http://localhost:8080`.
- For reproducibility, keep sample cases version-controlled.
