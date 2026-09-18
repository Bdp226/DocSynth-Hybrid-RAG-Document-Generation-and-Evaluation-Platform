# FAANG-Level Optimizations Without Changing Core App Code

This document captures the highest-leverage upgrades that improve engineering maturity, operability, and reviewer confidence without modifying the existing application logic.

## What was added

### 1. Cross-platform CI
- File: `.github/workflows/ci.yml`
- Runs the orchestrator test suite on Linux and Windows.
- Tests Python 3.11 and 3.12 to show interpreter portability.
- Adds a representative document-build smoke test so the project proves artifact generation, not only unit correctness.

### 2. Security pipeline
- File: `.github/workflows/security.yml`
- Adds weekly and change-triggered security checks.
- Runs `pip-audit` for dependency CVEs.
- Runs `bandit` against the orchestrator app for static security scanning.

### 3. Dependency hygiene
- File: `.github/dependabot.yml`
- Automates dependency and GitHub Actions update PRs.
- Signals active maintenance and supply-chain awareness.

### 4. PR quality gate
- File: `.github/pull_request_template.md`
- Forces every change to declare validation and regression checks.
- Preserves the project's core guarantees: no slide leaks, no roster leaks, and no accidental generated-artifact commits.

## Why this improves the rating

### Engineering maturity
These additions move the project beyond a strong prototype into a reviewable software artifact with repeatable verification and security posture.

### FAANG-style signals
Large companies look for more than a working demo. They look for:
- repeatable CI
- supply-chain controls
- security scanning
- clear review gates
- cross-platform validation
- explicit risk accounting

### What this still does not solve
These additions do not change runtime architecture. For a true 10/10 staff-level system, the next step would be to externalize document generation into a job queue with persistent work tracking, retries, and artifact lifecycle policies.

## Recommended next upgrades
1. Add a GitHub Actions artifact upload step for generated smoke-test PDFs.
2. Add repository rules requiring CI and security workflows before merge.
3. Add a design doc for async job orchestration with queue-backed execution.
4. Add benchmark history tracking for page count, topic count, image count, and leak counters.
