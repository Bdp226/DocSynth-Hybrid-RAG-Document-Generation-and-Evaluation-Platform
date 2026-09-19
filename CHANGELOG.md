# Changelog

All notable changes to DocSynth are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

## [1.0.0] — 2026-09-19

### Added — Production readiness

- **Health probes**: `GET /healthz` (liveness) and `GET /readyz` (readiness with
  LLM reachability, artifact-store writability, and model-availability checks)
  so the service can be safely orchestrated by Kubernetes.
- **`GET /version`**: build metadata endpoint exposing service version, git
  commit, build time, environment, and active model routing.
- **Rate limiting**: in-process sliding-window limiter keyed by identity with
  `Retry-After` and `X-RateLimit-*` response headers, configurable through
  `RATE_LIMIT_REQUESTS_PER_MINUTE`.
- **Request size guard**: rejects oversized payloads with HTTP 413 before they
  reach the generation pipeline.
- **CORS**: opt-in, origin-allow-listed CORS middleware (disabled by default).
- **Prometheus exposition**: `GET /metrics?format=prometheus` now returns the
  correct `text/plain; version=0.0.4` content type for scrapers.

### Added — Evaluation rigor

- **Quality gate**: `pipelines/eval/run_eval.py --gate` fails the build when any
  KPI drops below the thresholds in `pipelines/eval/thresholds.json`.
- **Golden regression set**: expanded from 2 to 12 labelled cases spanning
  executive summaries, status reports, procedures, risk registers, multi-source
  synthesis, compliance redaction, and adversarial/hallucination probes.
- **Per-case scoring**: coverage, forbidden-term leakage, structural compliance,
  grounding, and latency are scored independently per case.
- **Baseline comparison**: `--baseline` flag diffs a run against the committed
  report and reports per-KPI deltas.

### Added — Operational maturity

- **Tooling config** in `pyproject.toml`: ruff (lint + format), mypy, pytest,
  coverage with a 70% branch-coverage floor, and bandit.
- **`.pre-commit-config.yaml`** wiring ruff, mypy, bandit, and hygiene hooks.
- **`Makefile`** and `scripts/check.ps1` providing a single `check` entry point
  that mirrors CI exactly.
- **Hardened container**: multi-stage build, non-root `docsynth` user, pinned
  base digest-friendly layout, `HEALTHCHECK`, and OCI image labels.
- **`.dockerignore`** shrinking build context and preventing secret leakage.
- **CI expansion**: lint, type-check, coverage gate, container build, and
  quality-eval gate jobs added alongside the existing test matrix.

### Added — Documentation

- Architecture Decision Records under `docs/adr/`.
- `docs/slo-and-observability.md` defining SLIs, SLOs, error budgets, alerts,
  and the dashboard layout.
- `docs/evaluation-framework.md` describing the metric definitions, scoring
  methodology, and gate policy.
- `docs/demo-evidence.md` capturing sample outputs and before/after comparisons.
- `LICENSE` (MIT), `CONTRIBUTING.md`, and this changelog.

### Changed

- `requirements-dev.txt` now declares every tool CI runs (ruff, mypy,
  pytest-cov, bandit, pip-audit) so local and CI environments match.
- README restructured around problem → architecture → quality → operations →
  evidence.

---

## [0.1.0] — Initial engine

### Added

- FastAPI orchestrator with `/optimize`, `/compose`, async compose jobs, and
  authenticated artifact download.
- Hybrid BM25 + embedding retrieval over workspace files with chunk caching.
- PPTX/PDF ingestion with slide-accurate image extraction.
- Image triage separating informative figures from decorative clipart.
- PDF and DOCX rendering with inline figures, captions, and tables.
- Telemetry registry tracking 50+ KPIs with JSONL persistence.
- Policy guards for PII detection and input limits.
- Docker Compose and Kubernetes deployment manifests.
