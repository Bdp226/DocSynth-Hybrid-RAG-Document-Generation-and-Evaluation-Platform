"""Tests for the operational surface: liveness, readiness, version, and metrics.

These endpoints are contracts consumed by Kubernetes and Prometheus. Breaking
their shape silently breaks deployment automation, so they are pinned by tests.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import main
from app.config import SERVICE_NAME, SERVICE_VERSION, settings

client = TestClient(main.app)


# ---------------------------------------------------------------------------
# Liveness
# ---------------------------------------------------------------------------


def test_healthz_reports_liveness_without_touching_dependencies() -> None:
    response = client.get("/healthz")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ok"
    assert body["service"] == SERVICE_NAME
    assert body["version"] == SERVICE_VERSION
    assert body["uptime_seconds"] >= 0


def test_legacy_health_endpoint_is_preserved() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------


def test_readyz_is_ready_when_llm_is_optional(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "artifact_storage_dir", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "readiness_requires_llm", False)

    response = client.get("/readyz")
    body = response.json()

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["checks"]["artifact_store"]["ok"] is True


def test_readyz_returns_503_when_a_required_llm_is_unreachable(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(settings, "artifact_storage_dir", str(tmp_path / "artifacts"))
    monkeypatch.setattr(settings, "readiness_requires_llm", True)

    async def _no_models(force_refresh: bool = False) -> set[str]:
        return set()

    monkeypatch.setattr(main, "_installed_model_names", _no_models)

    response = client.get("/readyz")
    body = response.json()

    assert response.status_code == 503
    assert body["status"] == "not_ready"
    assert body["checks"]["llm_endpoint"]["ok"] is False


def test_readyz_fails_when_the_artifact_store_is_not_writable(monkeypatch, tmp_path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    # Pointing the artifact dir at a regular file makes mkdir fail, which is the
    # realistic shape of a bad volume mount.
    monkeypatch.setattr(settings, "artifact_storage_dir", str(blocker / "artifacts"))

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["checks"]["artifact_store"]["ok"] is False


# ---------------------------------------------------------------------------
# Version / build provenance
# ---------------------------------------------------------------------------


def test_version_exposes_build_and_routing_metadata() -> None:
    response = client.get("/version")
    body = response.json()

    assert response.status_code == 200
    assert body["service"] == SERVICE_NAME
    assert body["version"] == SERVICE_VERSION
    assert "git_commit" in body
    assert body["models"]["vision"] == settings.vision_model
    assert body["retrieval"]["top_k_chunks"] == settings.rag_top_k_chunks
    assert body["limits"]["max_request_bytes"] == settings.max_request_bytes


# ---------------------------------------------------------------------------
# Metrics exposition
# ---------------------------------------------------------------------------


def test_metrics_defaults_to_json_snapshot() -> None:
    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert isinstance(response.json(), dict)


def test_metrics_prometheus_format_uses_the_scraper_content_type() -> None:
    response = client.get("/metrics", params={"format": "prometheus"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in response.headers["content-type"]


def test_every_response_carries_a_request_id() -> None:
    response = client.get("/healthz")

    assert response.headers["X-Request-Id"]


def test_supplied_request_id_is_echoed_for_trace_correlation() -> None:
    response = client.get("/healthz", headers={"X-Request-Id": "trace-abc-123"})

    assert response.headers["X-Request-Id"] == "trace-abc-123"
