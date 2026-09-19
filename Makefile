# DocSynth developer task runner.
# Every target here mirrors a CI job exactly, so `make check` == green build.

PYTHON ?= python
ORCH   := services/orchestrator
APP    := $(ORCH)/app

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test cov security audit eval eval-gate check run docker-build docker-run clean demo

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime + dev dependencies and git hooks
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r $(ORCH)/requirements-dev.txt
	-pre-commit install

lint: ## Static lint (ruff)
	ruff check .

format: ## Auto-format the codebase
	ruff format .
	ruff check . --fix

typecheck: ## Static type analysis (mypy)
	mypy

test: ## Run the full test suite
	pytest

cov: ## Run tests with branch coverage and enforce the floor
	pytest --cov=app --cov-report=term-missing --cov-report=xml

security: ## Static application security testing
	bandit -c pyproject.toml -q -r $(APP)

audit: ## Dependency vulnerability audit
	pip-audit -r $(ORCH)/requirements.txt --strict

eval: ## Run the generation-quality evaluation harness
	$(PYTHON) pipelines/eval/run_eval.py

eval-gate: ## Run the evaluation harness and fail on KPI regressions
	$(PYTHON) pipelines/eval/run_eval.py --gate

check: lint typecheck cov security eval-gate ## Run every CI gate locally
	@echo "All quality gates passed."

run: ## Start the API locally with reload
	uvicorn services.orchestrator.app.main:app --host 127.0.0.1 --port 8080 --reload

demo: ## Produce demo artifacts and a fresh evaluation report
	$(PYTHON) $(ORCH)/scripts/check_compose_full_deck.py
	$(PYTHON) pipelines/eval/run_eval.py

docker-build: ## Build the hardened container image
	docker build -t docsynth/orchestrator:local $(ORCH)

docker-run: ## Run the full local stack
	docker compose -f deploy/docker-compose.yml up --build

clean: ## Remove caches and build output
	-rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	-find . -type d -name __pycache__ -prune -exec rm -rf {} +
