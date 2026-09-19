from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import main
from app.config import settings


client = TestClient(main.app)


def _headers(user_id: str = "user-001", role: str = "author") -> dict[str, str]:
    return {
        "X-User-Id": user_id,
        "X-User-Role": role,
    }


def test_document_title_never_echoes_the_prompt_or_slide_range() -> None:
    req = SimpleNamespace(
        user_prompt=(
            "Describe in professional way the full doc as per ppt slides and give "
            "from slide 81-144 and with images"
        ),
        objective="Produce complete publication-ready documentation from the deck",
        domain="enterprise platform",
    )
    records = [SimpleNamespace(title="A playground for AI agents' evaluation")]

    title = main._derive_document_title(req, records, ["Sandbox environment.pptx"])

    assert title == "A playground for AI agents' evaluation — Technical Documentation"
    assert "slide" not in title.lower()
    assert "describe" not in title.lower()


def test_document_title_falls_back_to_source_name_when_no_cover_title() -> None:
    req = SimpleNamespace(user_prompt="make me a pdf", objective="", domain="general")

    title = main._derive_document_title(req, [], ["Sandbox environment.pptx"])

    assert title == "Sandbox environment — Technical Documentation"


def test_topic_narrative_mentions_each_figure_with_descriptive_context() -> None:
    unit = main._TopicUnit(
        title="Environment Setup",
        lines=[
            "The sandbox provisions a dedicated VM with isolated network access.",
            "Operators validate connectivity, certificates, and permissions before onboarding users.",
        ],
        images=[SimpleNamespace(image_name="setup-figure.png")],
    )

    narrative = main._deterministic_topic_narrative(unit)

    assert "Figure" in narrative
    assert "illustrates" in narrative.lower()
    assert "setup-figure.png" not in narrative
    assert "isolated network access" in narrative


def test_document_title_uses_last_resort_when_nothing_usable() -> None:
    req = SimpleNamespace(user_prompt="generate docs", objective="", domain="general")

    assert main._derive_document_title(req, [], []) == "Technical Reference Documentation"


def test_optimize_success(monkeypatch) -> None:
    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        return "Optimized text"

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    response = client.post(
        "/optimize",
        headers=_headers(),
        json={
            "document_id": "d1",
            "text": "raw text",
            "objective": "improve",
            "domain": "general",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["optimized_text"] == "Optimized text"
    assert payload["model_used"] == settings.llm_model


def test_compose_rejects_invalid_image_base64(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        return "Optimized doc"

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "d2",
            "user_prompt": "make a report",
            "source_text": "",
            "instructions": ["use headers"],
            "objective": "report",
            "domain": "ops",
            "output_formats": ["docx"],
            "image_inputs": [
                {
                    "image_name": "bad.png",
                    "mime_type": "image/png",
                    "content_base64": "not-valid-base64",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "Invalid base64 image payload" in str(response.json())


def test_compose_and_download_authorization(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)
    call_prompts: list[str] = []

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        call_prompts.append(prompt)
        if model_override == settings.vision_model:
            return "Extracted image text"
        return "Final generated content"

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    response = client.post(
        "/compose",
        headers=_headers(user_id="owner-1", role="author"),
        json={
            "document_id": "d3",
            "user_prompt": "create summary",
            "source_text": "source",
            "instructions": ["be concise"],
            "objective": "summary",
            "domain": "clinical",
            "output_formats": ["docx"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifacts"]
    assert "workspace_sources" in payload
    assert "retrieval_chunks" in payload
    assert "retrieval_stats" in payload
    assert payload["retrieval_stats"]["selected_files"] >= 0
    assert len(call_prompts) >= 1
    artifact = payload["artifacts"][0]

    ok_download = client.get(artifact["download_path"], headers=_headers(user_id="owner-1", role="author"))
    assert ok_download.status_code == 200

    forbidden_download = client.get(artifact["download_path"], headers=_headers(user_id="other-user", role="author"))
    assert forbidden_download.status_code == 403


def test_benchmarks_endpoint_reads_eval_report(tmp_path: Path, monkeypatch) -> None:
    eval_dir = tmp_path / "pipelines" / "eval"
    eval_dir.mkdir(parents=True)
    report_path = eval_dir / "last_eval_report.json"
    report_path.write_text(
        json.dumps(
            {
                "mode": "mock",
                "summary": {"pass_rate": 1.0, "avg_latency_ms": 12.5},
                "results": [{"case_id": "c1", "ok": True}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "benchmark_report_path", report_path)

    response = client.get("/benchmarks")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["summary"]["pass_rate"] == 1.0
    assert payload["results"][0]["case_id"] == "c1"


def test_compose_comprehensive_mode_batches_generation(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)
    calls: list[str] = []

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        calls.append(prompt)
        if "Source Batch" in prompt:
            return "## Detailed Section\nFacts here"
        return "# Comprehensive Document\nExpanded final document"

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "d4",
            "user_prompt": "Create a comprehensive formal documentation package for sandbox setup and governance",
            "source_text": "seed source",
            "instructions": ["Preserve details"],
            "objective": "formal documentation",
            "domain": "clinical",
            "detail_level": "comprehensive",
            "output_formats": ["docx"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 200
    assert any("Source Batch" in prompt for prompt in calls)
    assert calls[-1].startswith("You are assembling a comprehensive final document")


def test_compose_dossier_mode_generates_multiple_chapters(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)
    calls: list[str] = []

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        calls.append(prompt)
        if prompt.startswith("You are writing the title page summary"):
            return "# Dossier Title\nIntro"
        if "Subsection Module:" in prompt:
            chapter_title = prompt.split("Chapter Title:", 1)[1].split("\n", 1)[0].strip()
            module_number = prompt.split("Subsection Module:", 1)[1].split("\n", 1)[0].strip()
            return f"### {chapter_title} Module {module_number}\nDetailed content"
        return "# Fallback"

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "d5",
            "user_prompt": "Create a long-form dossier for sandbox governance, architecture, onboarding, risks, and roadmap",
            "source_text": "seed source",
            "instructions": ["Preserve detail"],
            "objective": "formal documentation",
            "domain": "clinical",
            "detail_level": "dossier",
            "output_formats": ["docx"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 200
    assert any("Subsection Module:" in prompt for prompt in calls)
    assert sum(1 for prompt in calls if "Subsection Module:" in prompt) >= 12
    assert response.json()["retrieval_stats"]["generation_mode"] == "dossier"


def test_compose_rewrites_noisy_output_to_document_contract(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        return """Generated Document Draft
Reference Sources
Source Chunk: [Slide 12]
What we plan to do?
Author | Department
SHIFT ISE India
Random talkative conversation??
"""

    def fake_build_workspace_context(*args, **kwargs):
        chunks = [
            SimpleNamespace(
                chunk_id="sandbox.pdf#chunk-1",
                source="sandbox.pdf",
                score=0.91,
                text="The sandbox program establishes an isolated enterprise environment for controlled evaluation, onboarding, and governance reviews across multiple stakeholders.",
            ),
            SimpleNamespace(
                chunk_id="sandbox.pdf#chunk-2",
                source="sandbox.pdf",
                score=0.88,
                text="Mohd, Niharika, Kaushik, and Kiran discussed the sandbox requirements and next steps during the review meeting.",
            ),
            SimpleNamespace(
                chunk_id="sandbox.pdf#chunk-3",
                source="sandbox.pdf",
                score=0.86,
                text="Operational onboarding includes vendor coordination, access requests, environment provisioning, and review checkpoints for support ownership.",
            ),
            SimpleNamespace(
                chunk_id="sandbox.pdf#chunk-4",
                source="sandbox.pdf",
                score=0.84,
                text="Key risks include approval lead times, infrastructure dependencies, and security review delays, each requiring explicit mitigation tracking.",
            ),
        ]
        return "workspace context", ["sandbox.pdf"], chunks, SimpleNamespace(
            candidate_files=1,
            selected_files=1,
            chunks_scored=4,
            returned_chunks=4,
            cache_hits=0,
            cache_misses=1,
            context_chars=400,
            retrieval_latency_ms=5,
            top_score=0.91,
            avg_top_score=0.8725,
            used_embeddings=False,
        )

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)
    monkeypatch.setattr(main, "build_workspace_context", fake_build_workspace_context)

    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "d6",
            "user_prompt": "generate pdf comprehensive documentation",
            "source_text": "seed source",
            "instructions": ["Use formal tone"],
            "objective": "formal documentation",
            "domain": "clinical",
            "detail_level": "comprehensive",
            "output_formats": ["docx"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "document_contract_rewrite:compose" in payload["policy_flags"]
    assert "Generated Document Draft" not in payload["optimized_text"]
    assert "Reference Sources" not in payload["optimized_text"]
    assert "Source Chunk" not in payload["optimized_text"]
    assert "What we plan to do" not in payload["optimized_text"]
    assert "discussed the sandbox requirements" not in payload["optimized_text"]
    assert "## Executive Overview" in payload["optimized_text"]
    assert "## Publication Readiness Considerations" in payload["optimized_text"]


def test_compose_includes_workspace_ppt_images(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)
    captured = {}

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        if images:
            return "Recovered text from slide image"
        return "# Structured Document\n\n## Executive Overview\n\nFormal content"

    def fake_build_workspace_context(*args, **kwargs):
        return "workspace context", ["deck.pptx"], [], SimpleNamespace(
            candidate_files=1,
            selected_files=1,
            chunks_scored=0,
            returned_chunks=0,
            cache_hits=0,
            cache_misses=1,
            context_chars=20,
            retrieval_latency_ms=5,
            top_score=0.0,
            avg_top_score=0.0,
            used_embeddings=False,
        )

    def fake_extract_workspace_images_from_paths(*args, **kwargs):
        return [
            main.ImageInput(
                image_name="deck - Slide 2 - Image 1.png",
                mime_type="image/png",
                content_base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9VE3d2wAAAAASUVORK5CYII=",
            )
        ]

    def fake_generate_artifacts(document_id, text, formats, image_inputs=None):
        captured["image_inputs"] = image_inputs or []
        return []

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)
    monkeypatch.setattr(main, "build_workspace_context", fake_build_workspace_context)
    monkeypatch.setattr(main, "extract_workspace_images_from_paths", fake_extract_workspace_images_from_paths)
    monkeypatch.setattr(main, "generate_artifacts", fake_generate_artifacts)

    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "d7",
            "user_prompt": "generate pdf comprehensive documentation",
            "source_text": "",
            "instructions": [],
            "objective": "formal documentation",
            "domain": "general",
            "detail_level": "standard",
            "output_formats": ["pdf"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 400
    assert len(captured["image_inputs"]) == 1


def test_parse_topic_narratives_accepts_loose_markers() -> None:
    raw = (
        "- [topic 0]:\n"
        "This is a grounded narrative block that is comfortably longer than eighty characters so it is retained.\n\n"
        "[TOPIC 1]\n"
        "This is the second narrative block and it is also long enough to survive parsing and publication."
    )

    narratives = main._parse_topic_narratives(raw)

    assert narratives[0].startswith("This is a grounded narrative")
    assert narratives[1].startswith("This is the second narrative")


def test_full_deck_retries_missing_topics(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)
    calls: list[str] = []

    async def fake_generate(prompt: str, model_override=None, images=None) -> str:
        calls.append(prompt)
        if "[TOPIC 0]" in prompt and "[TOPIC 1]" in prompt:
            return (
                "[TOPIC 0]\n"
                "First topic narrative that is long enough to be retained and published as LLM-authored content."
            )
        if "[TOPIC 1]" in prompt:
            return (
                "[TOPIC 1]\n"
                "Second topic narrative recovered by the repair pass and long enough to replace fallback prose."
            )
        return ""

    slide_records = [
        SimpleNamespace(title="Overview", lines=["A" * 120], tables=[], images=[]),
        SimpleNamespace(title="Architecture", lines=["B" * 120], tables=[], images=[]),
    ]

    monkeypatch.setattr(main, "_generate_with_llm", fake_generate)

    result = asyncio.run(
        main._generate_full_deck_document(
            SimpleNamespace(objective="doc", domain="general"),
            slide_records,
            ["deck.pptx"],
            2,
            2,
        )
    )

    assert "First topic narrative" in result
    assert "Second topic narrative recovered by the repair pass" in result
    assert any("Do NOT omit any topic" in prompt for prompt in calls)


def test_compose_async_job_returns_persisted_result(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)

    async def fake_compose(req, ctx):
        return main.ComposeResponse(
            document_id=req.document_id,
            optimized_text="Background result",
            artifacts=[],
            policy_flags=[],
            model_used=settings.llm_model,
            image_text_snippets=[],
            workspace_sources=[],
            retrieval_chunks=[],
            retrieval_stats={"generation_mode": req.detail_level},
        )

    monkeypatch.setattr(main, "_compose_document", fake_compose)

    response = client.post(
        "/compose/jobs",
        headers=_headers(user_id="job-owner", role="author"),
        json={
            "document_id": "job-1",
            "user_prompt": "generate documentation",
            "source_text": "source",
            "instructions": [],
            "objective": "formal documentation",
            "domain": "general",
            "detail_level": "standard",
            "output_formats": ["pdf"],
            "image_inputs": [],
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] in {"queued", "running", "completed"}

    status = payload
    for _ in range(20):
        status = client.get(status["status_path"], headers=_headers(user_id="job-owner", role="author")).json()
        if status["status"] == "completed":
            break
        time.sleep(0.01)

    assert status["status"] == "completed"

    result = client.get(status["result_path"], headers=_headers(user_id="job-owner", role="author"))
    assert result.status_code == 200
    assert result.json()["optimized_text"] == "Background result"


def test_compose_async_job_enforces_owner(tmp_path: Path, monkeypatch) -> None:
    settings.artifact_storage_dir = str(tmp_path)

    async def fake_compose(req, ctx):
        return main.ComposeResponse(
            document_id=req.document_id,
            optimized_text="Background result",
            artifacts=[],
            policy_flags=[],
            model_used=settings.llm_model,
            image_text_snippets=[],
            workspace_sources=[],
            retrieval_chunks=[],
            retrieval_stats={},
        )

    monkeypatch.setattr(main, "_compose_document", fake_compose)

    response = client.post(
        "/compose/jobs",
        headers=_headers(user_id="job-owner", role="author"),
        json={
            "document_id": "job-2",
            "user_prompt": "generate documentation",
            "source_text": "source",
            "instructions": [],
            "objective": "formal documentation",
            "domain": "general",
            "detail_level": "standard",
            "output_formats": ["pdf"],
            "image_inputs": [],
        },
    )

    status_path = response.json()["status_path"]
    forbidden = client.get(status_path, headers=_headers(user_id="other-user", role="author"))
    assert forbidden.status_code == 403


def test_generate_with_llm_uses_disk_cache(tmp_path: Path, monkeypatch) -> None:
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"response": "Cached generation result"}

    class FakeClient:
        def __init__(self):
            self.posts = 0

        async def post(self, url, json):
            self.posts += 1
            return FakeResponse()

    fake_client = FakeClient()
    monkeypatch.setattr(main, "llm_cache_dir", tmp_path / "llm_cache")
    monkeypatch.setattr(main, "_model_availability_cache", {})
    monkeypatch.setattr(main.app.state, "http_client", fake_client, raising=False)

    first = asyncio.run(main._generate_with_llm("Prompt A"))
    second = asyncio.run(main._generate_with_llm("Prompt A"))

    assert first == "Cached generation result"
    assert second == "Cached generation result"
    assert fake_client.posts == 1


def test_generate_with_llm_short_circuits_missing_vision_model(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self):
            self.posts = 0

        async def post(self, url, json):
            self.posts += 1
            raise AssertionError("Vision short-circuit should happen before any POST")

    fake_client = FakeClient()
    monkeypatch.setattr(main, "llm_cache_dir", tmp_path / "llm_cache")
    monkeypatch.setattr(main, "_model_availability_cache", {})
    monkeypatch.setattr(main, "_installed_models_cache", None)
    monkeypatch.setattr(main.app.state, "http_client", fake_client, raising=False)
    async def fake_installed_models(force_refresh: bool = False):
        return {settings.llm_model}

    monkeypatch.setattr(main, "_installed_model_names", fake_installed_models)

    try:
        asyncio.run(main._generate_with_llm("Vision prompt", model_override=settings.vision_model, images=["abc"]))
    except main.HTTPException as exc:
        assert exc.status_code == 502
        assert "unavailable" in str(exc.detail)
    else:
        raise AssertionError("Expected missing vision model to raise HTTPException")

    assert fake_client.posts == 0


def test_resolve_vision_model_uses_fallback_when_configured_model_missing(monkeypatch) -> None:
    async def fake_installed_models(force_refresh: bool = False):
        return {"llava:7b", settings.llm_model}

    monkeypatch.setattr(main, "_installed_model_names", fake_installed_models)

    resolved = asyncio.run(main._resolve_vision_model())

    assert resolved == "llava:7b"


def test_capabilities_endpoint_reports_installed_and_resolved_models(monkeypatch) -> None:
    async def fake_installed_models(force_refresh: bool = False):
        return {settings.llm_model, "llava:7b"}

    async def fake_resolve_vision_model():
        return "llava:7b"

    monkeypatch.setattr(main, "_installed_model_names", fake_installed_models)
    monkeypatch.setattr(main, "_resolve_vision_model", fake_resolve_vision_model)

    response = client.get("/capabilities")

    assert response.status_code == 200
    payload = response.json()
    assert payload["configured_text_model"] == settings.llm_model
    assert payload["configured_vision_model"] == settings.vision_model
    assert payload["resolved_vision_model"] == "llava:7b"
    assert payload["text_model_available"] is True
    assert payload["vision_model_available"] is False
    assert "llava:7b" in payload["installed_models"]
    assert payload["background_jobs_enabled"] is True
