# Contributing to DocSynth

Thanks for helping improve DocSynth. This guide covers the local workflow, the
quality bar every change must clear, and how the CI gates are enforced.

---

## 1. Local setup

```powershell
git clone <repo-url>
cd "Agentic Doc automation"

python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r services\orchestrator\requirements-dev.txt
pre-commit install
```

Copy the environment template and adjust as needed:

```powershell
Copy-Item .env.example .env
```

---

## 2. The quality bar

Every pull request must satisfy the following gates. They run locally via
`make check` (or `pwsh scripts/check.ps1`) and again in CI.

| Gate | Command | Threshold |
|---|---|---|
| Lint | `ruff check .` | zero findings |
| Format | `ruff format --check .` | no diffs |
| Types | `mypy` | zero errors in `app/` |
| Unit + API tests | `pytest` | 100% pass |
| Coverage | `pytest --cov` | >= 70% branch coverage |
| Security (SAST) | `bandit -c pyproject.toml -r services/orchestrator/app` | no medium+ findings |
| Dependencies | `pip-audit` | no known high CVEs |
| Quality eval | `python pipelines/eval/run_eval.py --gate` | all KPI thresholds met |

A change that regresses a generation-quality KPI below the thresholds in
[pipelines/eval/thresholds.json](pipelines/eval/thresholds.json) will fail CI
even if every unit test passes. This is intentional: output quality is treated
as a build artifact, not a subjective judgement.

---

## 3. Making a change

1. **Branch** from `main` using `feat/`, `fix/`, `docs/`, `perf/`, or `chore/` prefixes.
2. **Write the test first** when fixing a bug — it should fail before your fix.
3. **Keep modules focused.** The service is organised by responsibility:
   retrieval, triage, generation, rendering, telemetry, policy. New behaviour
   belongs in the layer that owns it, not in `main.py`.
4. **Record a decision.** If you change an architectural boundary, add an ADR in
   [docs/adr/](docs/adr/) using the existing template.
5. **Update the changelog.** Add an entry to the `Unreleased` section of
   [CHANGELOG.md](CHANGELOG.md).

---

## 4. Commit convention

Conventional Commits are used to drive the changelog:

```
feat(retrieval): add reciprocal rank fusion to hybrid ranker
fix(builder): prevent duplicate captions in DOCX output
perf(cache): reuse parsed workspace files across compose calls
docs(adr): record decision to keep telemetry in-process
```

---

## 5. Code standards

- **Type hints** on all new public functions.
- **No network calls at import time.** All outbound I/O goes through the
  lifespan-managed `httpx.AsyncClient`.
- **Telemetry is best-effort.** Metrics capture must never fail a request —
  wrap it and log at debug level.
- **No secrets in code.** All configuration flows through `app/config.py`
  (`pydantic-settings`), which reads environment variables and `.env`.
- **Grounding is mandatory.** Any new generation path must record its source
  chunks so `groundedness_score` stays computable.

---

## 6. Running the service

```powershell
uvicorn services.orchestrator.app.main:app --host 127.0.0.1 --port 8080 --reload
```

Then open <http://127.0.0.1:8080/ui/>.

Useful endpoints while developing:

- `GET /healthz` — liveness
- `GET /readyz` — readiness, including LLM reachability
- `GET /version` — build metadata
- `GET /metrics?format=prometheus` — scrape-ready KPI exposition
- `GET /benchmarks` — latest evaluation snapshot

---

## 7. Reporting security issues

Do not open a public issue. Follow the process in [SECURITY.md](SECURITY.md).
