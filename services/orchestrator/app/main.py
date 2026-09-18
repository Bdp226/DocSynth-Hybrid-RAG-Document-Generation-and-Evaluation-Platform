from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.responses import FileResponse
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
import httpx

from .artifact_store import load_artifact, save_artifact
from .config import settings
from .document_builder import generate_artifacts
from .models import ComposeRequest, ComposeResponse, ImageInput, OptimizeRequest, OptimizeResponse
from .policy import detect_policy_flags, enforce_input_limits
from .security import RequestContext, get_request_context
from .telemetry import (
    MetricsRegistry,
    RunMetrics,
    Stopwatch,
    analyze_document,
    estimate_llm_authorship,
    image_triage,
    triage_delta,
)
from .workspace_context import (
    build_workspace_context,
    extract_pptx_slide_records,
    extract_workspace_images_from_paths,
    select_workspace_files,
)


logger = logging.getLogger("doc_optimizer.api")
job_state_dir = Path(__file__).resolve().parent.parent / "build" / "jobs"
llm_cache_dir = Path(__file__).resolve().parent.parent / "build" / "llm_cache"

# Observability sink for service-level KPIs. Recording is best-effort and never
# participates in request success or failure. The log lives under build/ so it is
# git-ignored and outside the retriever's workspace scope.
metrics_registry = MetricsRegistry(
    log_path=Path(__file__).resolve().parent.parent / "build" / "docsynth_metrics.jsonl"
)
_compose_jobs: dict[str, dict[str, object]] = {}
_model_availability_cache: dict[str, tuple[bool, float]] = {}
_installed_models_cache: tuple[set[str], float] | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=settings.llm_timeout_seconds)
    try:
        yield
    finally:
        await app.state.http_client.aclose()


app = FastAPI(title="Document Optimizer Orchestrator", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/ui", StaticFiles(directory=str(static_dir), html=True), name="ui")
workspace_root = Path(__file__).resolve().parents[3]
benchmark_report_path = workspace_root / "pipelines" / "eval" / "last_eval_report.json"


@app.middleware("http")
async def request_logging_middleware(request, call_next):
    request_id = request.headers.get("X-Request-Id", str(uuid4()))
    start = time.perf_counter()

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        status_code = 500
        raise
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log_record = {
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "user_id": request.headers.get("X-User-Id", "anonymous"),
        }
        logger.info(json.dumps(log_record, separators=(",", ":")))

    response.headers["X-Request-Id"] = request_id
    return response


def _normalize_base64(content: str) -> str:
    marker = "base64,"
    if marker in content:
        return content.split(marker, 1)[1].strip()
    return content.strip()


def _merge_image_inputs(primary: list[ImageInput], secondary: list[ImageInput], max_total: int = 12) -> list[ImageInput]:
    merged: list[ImageInput] = []
    seen: set[str] = set()

    for image in [*primary, *secondary]:
        normalized = _normalize_base64(image.content_base64)
        key = f"{image.image_name.lower()}::{normalized[:64]}::{len(normalized)}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(image)
        if len(merged) >= max_total:
            break

    return merged


def _generation_cache_path(cache_key: str) -> Path:
    return llm_cache_dir / f"{cache_key}.json"


def _cache_key_for_request(model_name: str, prompt: str, images: list[str] | None = None) -> str:
    digest = hashlib.sha256()
    digest.update(model_name.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(prompt.encode("utf-8"))
    for image in images or []:
        digest.update(b"\x00")
        digest.update(hashlib.sha256(image.encode("utf-8")).digest())
    return digest.hexdigest()


def _read_generation_cache(cache_key: str) -> str | None:
    if not settings.llm_cache_enabled:
        return None
    path = _generation_cache_path(cache_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    response = payload.get("response")
    if isinstance(response, str) and response.strip():
        return response.strip()
    return None


def _write_generation_cache(cache_key: str, *, model_name: str, prompt: str, response: str, image_count: int) -> None:
    if not settings.llm_cache_enabled:
        return
    try:
        llm_cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": model_name,
            "prompt_chars": len(prompt),
            "image_count": image_count,
            "response": response,
            "created_at": time.time(),
        }
        _generation_cache_path(cache_key).write_text(json.dumps(payload), encoding="utf-8")
        cached_files = sorted(llm_cache_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for stale in cached_files[settings.llm_cache_max_entries :]:
            stale.unlink(missing_ok=True)
    except OSError:
        return


async def _model_available(model_name: str) -> bool:
    names = await _installed_model_names()
    cached = _model_availability_cache.get(model_name)
    now = time.time()
    if cached and (now - cached[1]) <= settings.llm_capability_ttl_seconds:
        return cached[0]

    available = model_name in names

    _model_availability_cache[model_name] = (available, now)
    return available


async def _installed_model_names(force_refresh: bool = False) -> set[str]:
    global _installed_models_cache

    now = time.time()
    if not force_refresh and _installed_models_cache is not None:
        cached_names, cached_at = _installed_models_cache
        if (now - cached_at) <= settings.llm_capability_ttl_seconds:
            return set(cached_names)

    names: set[str] = set()
    try:
        response = await app.state.http_client.get(f"{settings.llm_base_url}/api/tags")
        response.raise_for_status()
        data = response.json()
        names = {
            item.get("name", "")
            for item in data.get("models", [])
            if isinstance(item, dict) and item.get("name")
        }
    except Exception:
        names = set()

    _installed_models_cache = (names, now)
    return set(names)


def _vision_model_candidates() -> list[str]:
    candidates = [settings.vision_model]
    candidates.extend(
        item.strip()
        for item in settings.vision_model_fallbacks.split(",")
        if item.strip()
    )
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


async def _resolve_vision_model() -> str | None:
    installed = await _installed_model_names()
    for candidate in _vision_model_candidates():
        if candidate in installed:
            return candidate
    for candidate in sorted(installed):
        lowered = candidate.lower()
        if "vision" in lowered or "llava" in lowered or "moondream" in lowered:
            return candidate
    return None


def _job_snapshot_path(job_id: str) -> Path:
    return job_state_dir / f"{job_id}.json"


def _persist_job_snapshot(job: dict[str, object]) -> None:
    job_state_dir.mkdir(parents=True, exist_ok=True)
    serializable = {key: value for key, value in job.items() if key != "task"}
    _job_snapshot_path(str(job["job_id"])).write_text(json.dumps(serializable), encoding="utf-8")


def _load_job_snapshot(job_id: str) -> dict[str, object] | None:
    in_memory = _compose_jobs.get(job_id)
    if in_memory is not None:
        return in_memory

    path = _job_snapshot_path(job_id)
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("status") in {"queued", "running"}:
        payload["status"] = "interrupted"
        payload["error"] = "The server restarted before the background job completed. Resubmit the request to continue."
        payload["updated_at"] = time.time()
        path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _require_job_owner(job: dict[str, object], user_id: str) -> None:
    if job.get("owner_user_id") != user_id:
        raise HTTPException(status_code=403, detail="This job belongs to a different user")


def _public_job_view(job: dict[str, object]) -> dict[str, object]:
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job.get("error"),
        "result_path": f"/compose/jobs/{job['job_id']}/result",
        "status_path": f"/compose/jobs/{job['job_id']}",
    }


def _fallback_compose_text(
    user_prompt: str,
    source_text: str,
    instructions: list[str],
    image_text_snippets: list[str],
    workspace_sources: list[str],
    retrieved_chunks=None,
    detail_level: str = "standard",
) -> str:
    def looks_conversational_sentence(text: str) -> bool:
        lowered = f" {text.lower()} "
        conversational_markers = [
            " discussed ",
            " introduced ",
            " asked ",
            " explained ",
            " mentioned ",
            " said ",
            " looping in ",
            " team members ",
            " speaker notes ",
        ]
        if any(marker in lowered for marker in conversational_markers):
            return True
        if re.search(r"\b[a-z]\s+days\b", lowered):
            return True
        if re.search(r"(?:\b[A-Z][a-z]+\b,\s*){2,}\b(?:and\s+)?[A-Z][a-z]+\b", text):
            return True
        return False

    def clean_sentence(text: str) -> str:
        normalized = re.sub(r"\[[^\]]+\]", "", text)
        normalized = re.sub(r"Source Chunk:\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bscore\s*=\s*[0-9.]+", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\b(?:image\s+[^:]+:|slide\s+\d+|title:)\s*", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\s+", " ", normalized).strip(" -:\n\t")
        return normalized

    def extract_fragments(chunk_text: str) -> list[str]:
        raw_parts = re.split(r"\n+|(?<=[.!?])\s+|\s+[|]\s+|;\s+", chunk_text)
        candidates: list[str] = []
        for part in raw_parts:
            sentence = clean_sentence(part)
            lowered = sentence.lower()
            if len(sentence) < 35:
                continue
            if len(sentence) > 280:
                continue
            if lowered.startswith(("author | department", "shift ise india", "siemens healthineers")):
                continue
            if sentence.endswith("?"):
                continue
            if " x days" in lowered or "lead time: x" in lowered or ".ext employees" in lowered:
                continue
            if looks_conversational_sentence(sentence):
                continue
            candidates.append(sentence)
        return candidates

    def dedupe_fragments(items: list[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for item in items:
            key = re.sub(r"\W+", " ", item.lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def prose_block(fragments: list[str], max_fragments: int, group_size: int = 2) -> list[str]:
        block = fragments[:max_fragments]
        if not block:
            return []
        paragraphs: list[str] = []
        for index in range(0, len(block), group_size):
            paragraphs.append(" ".join(block[index:index + group_size]))
        return paragraphs

    def blueprint_fragments(blueprint: dict[str, str | list[str]]) -> list[str]:
        fragments: list[str] = []
        section_chunks = _chunks_for_section(retrieved_chunks, blueprint, limit=8 if detail_level == "dossier" else 5)
        for chunk in section_chunks:
            fragments.extend(extract_fragments(chunk.text))
        if len(fragments) < (12 if detail_level == "dossier" else 6):
            for chunk in retrieved_chunks:
                fragments.extend(extract_fragments(chunk.text))
                if len(fragments) >= (18 if detail_level == "dossier" else 10):
                    break
        return dedupe_fragments(fragments)

    detail_title = "Formal Documentation Dossier" if detail_level == "dossier" else "Formal Documentation"
    title = user_prompt.strip().title() if user_prompt.strip() and len(user_prompt.split()) > 2 else detail_title
    lines: list[str] = [f"# {title}", ""]

    lines.append("## Objective")
    lines.append(clean_sentence(user_prompt) or "Generate a structured, publication-ready document from the available evidence.")
    lines.append("")

    if retrieved_chunks:
        lines.append("## Executive Overview")
        lines.append("")
        overview_fragments: list[str] = []
        for chunk in retrieved_chunks[: min(len(retrieved_chunks), 10 if detail_level == "dossier" else 6)]:
            overview_fragments.extend(extract_fragments(chunk.text))
        overview_fragments = dedupe_fragments(overview_fragments)
        for paragraph in prose_block(overview_fragments, 10 if detail_level == "dossier" else 6, group_size=2):
            lines.append(paragraph)
        lines.append("")

        for blueprint in _section_blueprints()[: 12 if detail_level == "dossier" else 8]:
            section_fragments = blueprint_fragments(blueprint)
            if not section_fragments:
                continue
            lines.append(f"## {blueprint['title']}")
            lines.append("")
            lines.append(str(blueprint["guidance"]))
            lines.append("")
            for paragraph in prose_block(section_fragments, 18 if detail_level == "dossier" else 8, group_size=2):
                lines.append(paragraph)
            lines.append("")
    elif source_text.strip():
        lines.append("## Documented Findings")
        lines.append("")
        source_fragments = dedupe_fragments(extract_fragments(source_text))
        for paragraph in prose_block(source_fragments, 20 if detail_level == "dossier" else 12, group_size=2):
            lines.append(paragraph)
        lines.append("")

    if image_text_snippets:
        lines.append("## Image-Derived Findings")
        lines.append("")
        for item in image_text_snippets[:8]:
            cleaned_item = clean_sentence(item)
            if cleaned_item and not looks_conversational_sentence(cleaned_item):
                lines.append(f"- {cleaned_item}")
        lines.append("")

    lines.append("## Publication Readiness Considerations")
    lines.append("")
    lines.append("- Validate names, figures, and vendor-specific details before publication.")
    lines.append("- Confirm approval, security, and environment setup facts against the latest source documents.")
    lines.append("- Ensure the final release version uses enterprise-approved wording and section ordering.")
    return "\n".join(lines).strip()


def _augment_short_output(optimized: str, req: ComposeRequest, retrieved_chunks, image_text_snippets: list[str]) -> str:
    if req.detail_level not in {"comprehensive", "dossier"}:
        return optimized
    min_chars = 18000 if req.detail_level == "dossier" else 9000
    if len(optimized.strip()) >= min_chars:
        return optimized

    appendix = _fallback_compose_text(
        user_prompt=req.user_prompt,
        source_text=optimized,
        instructions=req.instructions,
        image_text_snippets=image_text_snippets,
        workspace_sources=[],
        retrieved_chunks=retrieved_chunks,
        detail_level=req.detail_level,
    )
    appendix_body = "\n".join(line for line in appendix.splitlines() if not line.startswith("# ")).strip()
    return f"{optimized.strip()}\n\n## Expanded Supporting Detail\n\n{appendix_body}"


def _postprocess_document_text(text: str) -> str:
    cleaned_lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if not line:
            if cleaned_lines and cleaned_lines[-1] != "":
                cleaned_lines.append("")
            continue
        # Structured rows, headings and figure tokens are generated content, not extracted noise.
        if line.startswith("|") or line.startswith("[[IMAGE:") or line.startswith("#"):
            cleaned_lines.append(line)
            continue
        if re.match(r"^Source Chunk:\s*", line, re.IGNORECASE):
            continue
        if re.match(r"^\[Slide\s+\d+\]$", line, re.IGNORECASE):
            continue
        if re.match(r"^Author\s*\|\s*Department$", line, re.IGNORECASE):
            continue
        if re.match(r"^SHIFT\s+ISE\s+India$", line, re.IGNORECASE):
            continue
        if re.match(r"^What\s+we\s+plan\s+to\s+do\??$", line, re.IGNORECASE):
            continue
        if _MEETING_CHATTER_RE.search(line):
            continue
        if re.search(r"(?:\b[A-Z][a-z]+\b,\s*){2,}\b(?:and\s+)?[A-Z][a-z]+\b", line):
            continue
        if re.search(r"\b[A-Z]\s+Days\b", line):
            continue
        if line.count("?") >= 2:
            continue
        key = line.lower()
        if key in seen and len(line) < 140:
            continue
        seen.add(key)
        cleaned_lines.append(line)
    while cleaned_lines and cleaned_lines[-1] == "":
        cleaned_lines.pop()
    return "\n".join(cleaned_lines)


def _contains_banned_document_markers(text: str) -> bool:
    banned_patterns = [
        r"(?im)^generated document draft$",
        r"(?im)^reference sources$",
        r"(?im)^evidence appendix$",
        r"(?im)^authoring instructions applied$",
        r"(?im)\bsource chunk\b",
        r"(?im)^\[slide\s+\d+\]$",
        r"(?im)^author\s*\|\s*department$",
        r"(?im)^shift\s+ise\s+india$",
        r"(?im)^what\s+we\s+plan\s+to\s+do\??$",
        r"(?im)^workspace sources\s*:",
    ]
    if any(re.search(pattern, text) for pattern in banned_patterns):
        return True
    return bool(_MEETING_CHATTER_RE.search(text))


def _violates_document_contract(text: str, detail_level: str, has_retrieved_chunks: bool) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("# "):
        return True
    if _contains_banned_document_markers(stripped):
        return True

    section_count = sum(1 for line in lines if line.startswith("## "))
    if detail_level == "dossier":
        minimum_sections = 6 if has_retrieved_chunks else 3
        if section_count < minimum_sections:
            return True
    elif detail_level == "comprehensive":
        minimum_sections = 4 if has_retrieved_chunks else 3
        if section_count < minimum_sections:
            return True

    return False


def _finalize_document_text(
    optimized: str,
    *,
    effective_prompt: str,
    seed_text: str,
    effective_instructions: list[str],
    image_text_snippets: list[str],
    workspace_sources: list[str],
    retrieved_chunks,
    detail_level: str,
) -> tuple[str, bool]:
    cleaned = _postprocess_document_text(optimized)
    if not _violates_document_contract(cleaned, detail_level, bool(retrieved_chunks)):
        return cleaned, False

    rebuilt = _fallback_compose_text(
        user_prompt=effective_prompt,
        source_text=seed_text,
        instructions=effective_instructions,
        image_text_snippets=image_text_snippets,
        workspace_sources=workspace_sources,
        retrieved_chunks=retrieved_chunks,
        detail_level=detail_level,
    )
    return _postprocess_document_text(rebuilt), True


def _looks_generic_prompt(prompt: str) -> bool:
    tokens = [token for token in re.findall(r"[a-zA-Z0-9_]+", prompt.lower()) if token]
    generic_terms = {"generate", "pdf", "doc", "document", "documentation", "comprehensive", "report", "file"}
    if len(tokens) <= 5 and all(token in generic_terms for token in tokens):
        return True
    return False


def _professional_authoring_brief(req: ComposeRequest, workspace_sources: list[str]) -> tuple[str, str, list[str]]:
    prompt = req.user_prompt.strip()
    objective = req.objective.strip() or "Produce publication-ready formal documentation"
    instructions = [item.strip() for item in req.instructions if item.strip()]

    if not _looks_generic_prompt(prompt):
        return prompt, objective, instructions

    inferred_scope = "the workspace source materials"
    if workspace_sources:
        inferred_scope = ", ".join(workspace_sources[:3])

    prompt = (
        "Create a professional formal documentation package based on the available Siemens Healthineers workspace materials, "
        "covering purpose, scope, architecture, governance, workflow, risks, implementation steps, and next actions."
    )
    objective = "Generate comprehensive professional documentation suitable for enterprise review and PDF publication"
    default_instructions = [
        "Use formal enterprise documentation tone",
        "Organize the document into clear sections and actionable steps",
        "Exclude raw retrieval metadata, slide tags, and meeting-style conversational fragments",
        f"Ground the content in {inferred_scope}",
    ]
    return prompt, objective, [*default_instructions, *instructions]


def _build_retrieval_query(req: ComposeRequest) -> str:
    parts = [req.user_prompt.strip(), req.objective.strip(), req.domain.strip()]
    parts.extend(item.strip() for item in req.instructions if item.strip())
    parts.extend(item.strip() for item in req.workspace_file_hints if item.strip())
    if req.source_text.strip():
        parts.append(req.source_text.strip()[:800])
    return "\n".join(part for part in parts if part)


def _generation_profile(req: ComposeRequest) -> dict[str, int | str | bool]:
    if req.detail_level == "full_deck":
        return {
            "mode": "full_deck",
            "max_docs": max(4, min(req.max_workspace_docs, 8)),
            "max_chars_total": 16000,
            "max_chars_per_doc": 14000,
            "top_k_chunks": max(6, min(settings.rag_top_k_chunks, 10)),
        }
    if req.detail_level == "summary":
        return {
            "mode": "single_pass",
            "max_docs": max(3, min(req.max_workspace_docs, 5)),
            "max_chars_total": 12000,
            "max_chars_per_doc": 10000,
            "top_k_chunks": max(6, min(settings.rag_top_k_chunks, 8)),
        }
    if req.detail_level == "standard":
        return {
            "mode": "single_pass",
            "max_docs": max(5, req.max_workspace_docs),
            "max_chars_total": 22000,
            "max_chars_per_doc": 18000,
            "top_k_chunks": max(settings.rag_top_k_chunks, 10),
        }
    if req.detail_level == "comprehensive":
        return {
            "mode": "sectioned_comprehensive",
            "max_docs": max(8, req.max_workspace_docs),
            "max_chars_total": 42000,
            "max_chars_per_doc": 30000,
            "top_k_chunks": max(settings.rag_top_k_chunks, 16),
        }
    return {
        "mode": "dossier",
        "max_docs": max(16, req.max_workspace_docs),
        "max_chars_total": 100000,
        "max_chars_per_doc": 60000,
        "top_k_chunks": max(settings.rag_top_k_chunks, 48),
    }


def _section_blueprints() -> list[dict[str, str | list[str]]]:
    return [
        {
            "title": "Executive Overview",
            "keywords": ["overview", "summary", "purpose", "context", "pilot", "sandbox"],
            "guidance": "Explain the business context, intended outcomes, scope, and why the sandbox initiative exists.",
        },
        {
            "title": "Program Objectives and Scope",
            "keywords": ["objective", "scope", "business", "evaluation", "workflow", "lifecycle"],
            "guidance": "Capture explicit objectives, evaluation boundaries, stakeholders, and what the sandbox is meant to enable.",
        },
        {
            "title": "Architecture and Environment Design",
            "keywords": ["architecture", "vm", "environment", "network", "azure", "cluster", "infrastructure"],
            "guidance": "Document technical architecture, network isolation, VM setup, cloud choices, and system components.",
        },
        {
            "title": "Platform Components and Integration Boundaries",
            "keywords": ["integration", "component", "repository", "service", "llm", "endpoint", "api"],
            "guidance": "Describe system modules, integration points, interfaces, and how the sandbox interacts with enterprise tooling.",
        },
        {
            "title": "Governance, Approvals, and Compliance",
            "keywords": ["approval", "governance", "itccs", "compliance", "legal", "security", "access"],
            "guidance": "Describe approval paths, compliance gates, access control, vendor onboarding approvals, and review responsibilities.",
        },
        {
            "title": "Security, Identity, and Access Control",
            "keywords": ["security", "identity", "access", "role", "network", "policy", "guardrail"],
            "guidance": "Cover identity handling, network isolation, authorization controls, policy checks, and operational security measures.",
        },
        {
            "title": "Operational Workflow and Onboarding",
            "keywords": ["onboarding", "process", "workflow", "vendor", "setup", "author", "billing"],
            "guidance": "Lay out end-to-end onboarding, environment provisioning, handoffs, billing, and operational ownership steps.",
        },
        {
            "title": "Infrastructure Provisioning and Resource Planning",
            "keywords": ["resource", "provision", "vm", "capacity", "billing", "cost", "environment"],
            "guidance": "Explain provisioning flows, resource sizing, cost or billing considerations, VM planning, and infrastructure ownership.",
        },
        {
            "title": "Challenges, Constraints, and Tradeoffs",
            "keywords": ["challenge", "constraint", "risk", "tradeoff", "delay", "limitation", "lead time"],
            "guidance": "Include setup blockers, negotiation issues, security constraints, infrastructure tradeoffs, and schedule impacts.",
        },
        {
            "title": "Risk Register and Mitigations",
            "keywords": ["risk", "mitigation", "security", "dependency", "support", "owner", "monitoring"],
            "guidance": "Produce a detailed risk-oriented section with concrete mitigations, owners, and failure scenarios.",
        },
        {
            "title": "Evaluation Strategy and Benchmarking",
            "keywords": ["evaluation", "benchmark", "quality", "metric", "accuracy", "coverage", "test"],
            "guidance": "Summarize how success is measured, what benchmarking signals matter, and how evaluation workflows are organized.",
        },
        {
            "title": "Operational Support Model",
            "keywords": ["support", "owner", "responsibility", "handoff", "operations", "maintenance", "monitoring"],
            "guidance": "Describe ownership, support escalation paths, maintenance responsibilities, and operational continuity planning.",
        },
        {
            "title": "Implementation Roadmap and Next Steps",
            "keywords": ["next", "roadmap", "future", "plan", "phase", "improve", "benchmark"],
            "guidance": "Close with implementation sequencing, readiness gaps, and recommended next execution steps.",
        },
    ]


def _score_chunk_for_section(chunk_text: str, blueprint: dict[str, str | list[str]]) -> int:
    lowered = chunk_text.lower()
    score = 0
    for keyword in blueprint["keywords"]:
        if keyword in lowered:
            score += 1
    return score


def _chunks_for_section(retrieved_chunks, blueprint: dict[str, str | list[str]], limit: int = 6):
    ranked = sorted(
        retrieved_chunks,
        key=lambda item: (_score_chunk_for_section(item.text, blueprint), item.score),
        reverse=True,
    )
    chosen = [item for item in ranked if _score_chunk_for_section(item.text, blueprint) > 0][:limit]
    if len(chosen) < min(limit, len(retrieved_chunks)):
        fallback = [item for item in ranked if item not in chosen][: max(0, limit - len(chosen))]
        chosen.extend(fallback)
    return chosen[:limit]


def _batch_items(items, batch_size: int):
    return [items[index:index + batch_size] for index in range(0, len(items), batch_size) if items[index:index + batch_size]]


def _topic_prompt_payload(index: int, unit: object) -> str:
    body = "\n".join(f"- {line}" for line in unit.lines[:22])
    if not body:
        body = "- (This topic is conveyed through diagrams or tables rather than body text.)"
    extras = []
    if unit.tables:
        extras.append(f"{len(unit.tables)} table(s) will be shown with your text")
    if unit.images:
        extras.append(f"{len(unit.images)} figure(s) will be shown with your text")
    extra_note = ("; ".join(extras) + ".") if extras else "No figures or tables accompany this topic."
    return f"[TOPIC {index}] Subject: {unit.title}\n{extra_note}\nCaptured content:\n{body}"


async def _render_topic_batches(
    req: ComposeRequest,
    indexed_units: list[tuple[int, object]],
    *,
    batch_size: int,
    max_concurrency: int,
    repair_mode: bool = False,
) -> dict[int, str]:
    batches = _batch_items(indexed_units, batch_size)
    semaphore = asyncio.Semaphore(max_concurrency)

    async def render_batch(batch) -> str:
        payloads = [_topic_prompt_payload(index, unit) for index, unit in batch]
        rules = (
            "Hard rules:\n"
            "- Begin each topic's block with the exact marker [TOPIC <number>] on its own line.\n"
            "- Do NOT write markdown headings, bullet lists, or tables; return prose paragraphs only.\n"
            "- Never refer to slides, slide numbers, decks, or presentations. Write as standalone documentation.\n"
            "- Explain what the topic establishes, why it matters, and how it fits the wider process.\n"
            "- Use ONLY the captured content provided. Never invent facts, dates, figures, names, or outcomes.\n"
            "- Never mention meetings, attendees, personal names, speakers, or who said what.\n"
            "- Use formal third-person documentation tone with no conversational phrasing.\n"
        )
        if repair_mode:
            rules += (
                "- Do NOT omit any topic. If the source is sparse, still write 120 to 220 words grounded in the available evidence.\n"
                "- Repeat the marker exactly as given before every topic body.\n"
            )
        prompt = (
            "You are writing a formal enterprise reference manual in the style of a textbook chapter. "
            "For EACH topic provided, write 180 to 300 words of flowing explanatory prose.\n\n"
            f"{rules}\n"
            f"Document objective: {req.objective}\n"
            f"Domain: {req.domain}\n\n"
            "Topics to document:\n\n" + "\n\n".join(payloads)
        )

        try:
            async with semaphore:
                return await _generate_with_llm(prompt)
        except HTTPException:
            return ""

    responses = await asyncio.gather(*(render_batch(batch) for batch in batches))
    narratives: dict[int, str] = {}
    for response in responses:
        narratives.update(_parse_topic_narratives(response))
    return narratives


def _source_evidence_appendix(retrieved_chunks, source_limit: int = 6, chunk_limit_per_source: int = 5) -> str:
    grouped: dict[str, list] = {}
    for item in retrieved_chunks:
        grouped.setdefault(item.source, []).append(item)

    lines = ["## Evidence Appendix", ""]
    ranked_sources = sorted(grouped.items(), key=lambda pair: max(chunk.score for chunk in pair[1]), reverse=True)
    for source_name, items in ranked_sources[:source_limit]:
        lines.append(f"### {source_name}")
        lines.append("")
        for chunk in items[:chunk_limit_per_source]:
            preview = " ".join(chunk.text.strip().split())[:420]
            lines.append(f"- {chunk.chunk_id} (score={chunk.score}): {preview}")
        lines.append("")
    return "\n".join(lines).strip()


async def _generate_comprehensive_document(
    req: ComposeRequest,
    seed_text: str,
    workspace_sources: list[str],
    retrieved_chunks,
    image_context: str,
) -> str:
    chunk_batches = [retrieved_chunks[index:index + 4] for index in range(0, min(len(retrieved_chunks), 16), 4)]
    section_drafts: list[str] = []

    for batch_index, batch in enumerate(chunk_batches, start=1):
        chunk_context = "\n\n".join(
            f"Source: {item.chunk_id}\n{item.text.strip()}" for item in batch
        )
        batch_prompt = (
            "You are drafting one detailed section of a formal enterprise document. "
            "Use the retrieved source material exhaustively instead of summarizing it away. "
            "Preserve concrete process details, governance steps, architecture notes, constraints, and operational facts. "
            "Return section content only in clean markdown with a heading and useful bullets where appropriate.\n\n"
            f"Document Objective: {req.objective}\n"
            f"Domain: {req.domain}\n"
            f"User Prompt: {req.user_prompt}\n"
            f"Instructions:\n{chr(10).join(f'- {item}' for item in req.instructions if item.strip()) or '- None'}\n\n"
            f"Source Batch {batch_index}:\n{chunk_context}\n\n"
            f"Image Notes:\n{image_context if image_context else '- None'}"
        )
        section_drafts.append(await _generate_with_llm(batch_prompt))

    final_prompt = (
        "You are assembling a comprehensive final document from vetted section drafts and source notes. "
        "Do not compress this into a short executive summary. "
        "Produce a substantial, fully structured formal document with broad source coverage. "
        "Include sections for overview, motivation, scope, process or architecture, governance and approvals, challenges, risks, operational details, and next steps. "
        "If image notes exist, integrate them into the body and add an image appendix section. "
        "Return only final document content in markdown.\n\n"
        f"User Prompt: {req.user_prompt}\n"
        f"Objective: {req.objective}\n"
        f"Domain: {req.domain}\n"
        f"Workspace Sources: {', '.join(workspace_sources) if workspace_sources else '- None'}\n\n"
        f"Seed Text:\n{seed_text[:4000]}\n\n"
        f"Section Drafts:\n\n{chr(10).join(section_drafts)}\n\n"
        f"Image Notes:\n{image_context if image_context else '- None'}"
    )
    return await _generate_with_llm(final_prompt)


async def _generate_dossier_document(
    req: ComposeRequest,
    seed_text: str,
    workspace_sources: list[str],
    retrieved_chunks,
    image_context: str,
    image_text_snippets: list[str],
) -> str:
    blueprints = _section_blueprints()
    section_outputs: list[str] = []

    intro_prompt = (
        "You are writing the title page summary and document intent for a long-form enterprise dossier. "
        "Return a substantial title section and executive preface in markdown. Do not abbreviate the scope.\n\n"
        f"User Prompt: {req.user_prompt}\n"
        f"Objective: {req.objective}\n"
        f"Domain: {req.domain}\n"
        f"Workspace Sources: {', '.join(workspace_sources) if workspace_sources else '- None'}\n"
        f"Seed Text: {seed_text[:2500]}"
    )
    preface = await _generate_with_llm(intro_prompt)

    for blueprint in blueprints:
        section_chunks = _chunks_for_section(retrieved_chunks, blueprint, limit=8)
        module_outputs: list[str] = []
        for module_index, module_chunks in enumerate(_batch_items(section_chunks, 2), start=1):
            chunk_context = "\n\n".join(
                f"Source: {item.chunk_id}\n{item.text.strip()}" for item in module_chunks
            )
            module_prompt = (
                "You are drafting one subsection module of a long-form formal documentation package. "
                "Write a dense, specific, source-grounded subsection of roughly 220 to 420 words. "
                "Preserve concrete details, named processes, architecture notes, approvals, constraints, and operational facts from the sources. "
                "Return markdown only beginning with a level-3 heading.\n\n"
                f"Chapter Title: {blueprint['title']}\n"
                f"Subsection Module: {module_index}\n"
                f"Chapter Guidance: {blueprint['guidance']}\n"
                f"User Prompt: {req.user_prompt}\n"
                f"Objective: {req.objective}\n"
                f"Domain: {req.domain}\n"
                f"Instructions:\n{chr(10).join(f'- {item}' for item in req.instructions if item.strip()) or '- None'}\n\n"
                f"Relevant Source Material:\n{chunk_context}\n\n"
                f"Image Notes:\n{image_context if image_context else '- None'}"
            )
            module_outputs.append(await _generate_with_llm(module_prompt))

        chapter_lines = [f"## {blueprint['title']}", ""]
        for module_text in module_outputs:
            if module_text.strip():
                chapter_lines.append(module_text.strip())
                chapter_lines.append("")
        section_outputs.append("\n".join(chapter_lines).strip())

    appendix_lines: list[str] = []
    if image_text_snippets:
        appendix_lines.append("## Image-Derived Findings")
        appendix_lines.append("")
        appendix_lines.extend(image_text_snippets)
        appendix_lines.append("")

    assembled = [preface.strip(), *[section.strip() for section in section_outputs if section.strip()]]
    if appendix_lines:
        assembled.append("\n".join(appendix_lines).strip())
    return "\n\n".join(part for part in assembled if part)


_PART_TAXONOMY: list[tuple[str, tuple[str, ...]]] = [
    (
        "Programme Overview and Objectives",
        ("overview", "objective", "vision", "introduction", "playground", "evaluate", "evaluation",
         "accelerat", "current state", "assessment", "way forward", "executive", "scope", "goal"),
    ),
    (
        "Commercial Onboarding and Compliance",
        ("nda", "pilot agreement", "vendor", "onboarding", "compliance", "procurement", "po release",
         "purchase order", "contract", "legal", "dpia", "gdpr", "supplier"),
    ),
    (
        "Solution Architecture and Data Flow",
        ("architecture", "data flow", "dataflow", "design", "component", "integration", "topology",
         "landscape", "diagram", "blueprint"),
    ),
    (
        "Environment Setup and Configuration",
        ("set-up", "setup", "provision", "install", "configure", "configuration", "fqdn", "domain name",
         "ssl", "certificate", "virtual machine", "network", "firewall", "access", "vpn", "server"),
    ),
    (
        "Tooling and Platform Capabilities",
        ("tool", "dashboard", "agent", "potpie", "feature", "capability", "use case", "demo",
         "metric", "hub", "copilot", "model"),
    ),
    (
        "Cost, Budget and Effort",
        ("cost", "budget", "usd", "effort", "hours", "pricing", "licence", "license", "invoice", "spend"),
    ),
    (
        "Security, Risk and Governance",
        ("security", "risk", "governance", "approval", "policy", "audit", "privacy", "threat",
         "mitigat", "control", "confidential"),
    ),
    (
        "Programme Status and Milestones",
        ("status", "milestone", "timeline", "roadmap", "plan", "progress", "update", "next step",
         "kick-off", "kickoff", "schedule"),
    ),
]
_DEFAULT_PART_TITLE = "Supporting Reference Material"

# Columns holding personnel or freeform commentary are dropped so tables stay about the work.
_OMIT_COLUMN_RE = re.compile(
    r"^(responsible|owner|assignee|person|people|participants?|attendees?|contact|reporter"
    r"|comments?(\s*/?\s*next\s*steps?)?|next\s*steps?|remarks?|notes?)$",
    re.IGNORECASE,
)
_STEP_TITLE_RE = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+(.{3,})$")

# Meeting chatter is a named participant performing a reporting verb, e.g. "Kaushik explained ...".
# Matching the bare verbs would also strike legitimate prose such as "where they are explained".
_MEETING_CHATTER_RE = re.compile(
    r"(?i:\blooping\s+in\b)"
    r"|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:has\s+|have\s+|had\s+)?"
    r"(?:discussed|introduced|asked|explained|mentioned)\b",
)


@dataclass
class _TopicUnit:
    """A consolidated documentation topic merged from one or more consecutive slides."""

    title: str
    lines: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    images: list[ImageInput] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.lines or self.tables or self.images)


def _merge_slide_records_into_topics(slide_records: list) -> list[_TopicUnit]:
    """Collapse repeated/continued slides into single topics so output is part-wise, not slide-wise."""
    units: list[_TopicUnit] = []

    for record in slide_records:
        title = (record.title or "").strip()
        key = title.lower()
        previous = units[-1] if units else None

        # Untitled continuation slides and repeated titles fold into the preceding topic.
        same_as_previous = previous is not None and key and key == previous.title.lower()
        continuation = previous is not None and not title

        if previous is not None and (same_as_previous or continuation):
            target = previous
        else:
            target = _TopicUnit(title=title or "Overview")
            units.append(target)

        existing = {line.lower() for line in target.lines}
        for line in record.lines:
            key_line = line.lower()
            if key_line in existing:
                continue
            existing.add(key_line)
            target.lines.append(line)

        target.tables.extend(record.tables)
        target.images.extend(record.images)

    # Second pass: topics with the same subject appearing later in the source are folded together
    # so each subject is documented once, in full, rather than repeated under duplicate headings.
    consolidated: list[_TopicUnit] = []
    by_title: dict[str, _TopicUnit] = {}

    for unit in units:
        key = unit.title.strip().lower()
        primary = by_title.get(key)
        if primary is None:
            by_title[key] = unit
            consolidated.append(unit)
            continue

        existing = {line.lower() for line in primary.lines}
        for line in unit.lines:
            if line.lower() in existing:
                continue
            existing.add(line.lower())
            primary.lines.append(line)
        primary.tables.extend(unit.tables)
        primary.images.extend(unit.images)

    return [unit for unit in consolidated if unit.has_content]


def _classify_topic_part(unit: _TopicUnit) -> str:
    haystack = " ".join([unit.title.lower()] * 3 + [line.lower() for line in unit.lines[:8]])
    best_title = _DEFAULT_PART_TITLE
    best_score = 0

    for part_title, keywords in _PART_TAXONOMY:
        score = sum(haystack.count(keyword) for keyword in keywords)
        if score > best_score:
            best_score = score
            best_title = part_title

    return best_title


def _group_topics_into_parts(units: list[_TopicUnit]) -> list[tuple[str, list[_TopicUnit]]]:
    buckets: dict[str, list[_TopicUnit]] = {}
    for unit in units:
        buckets.setdefault(_classify_topic_part(unit), []).append(unit)

    ordered: list[tuple[str, list[_TopicUnit]]] = []
    for part_title, _ in _PART_TAXONOMY:
        if buckets.get(part_title):
            ordered.append((part_title, buckets[part_title]))
    if buckets.get(_DEFAULT_PART_TITLE):
        ordered.append((_DEFAULT_PART_TITLE, buckets[_DEFAULT_PART_TITLE]))
    return ordered


def _render_markdown_table(table: list[list[str]], max_cell_chars: int = 90) -> list[str]:
    """Render a slide table as a markdown pipe table, omitting personnel columns."""
    if not table or len(table) < 2:
        return []

    header = table[0]
    keep = [index for index, cell in enumerate(header) if not _OMIT_COLUMN_RE.match(cell.strip())]
    if len(keep) < 2:
        keep = list(range(len(header)))

    def clean(value: str) -> str:
        text = re.sub(r"\s+", " ", value or "").replace("|", "/").strip()
        text = re.sub(r"\*{2,}", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > max_cell_chars:
            text = text[:max_cell_chars].rsplit(" ", 1)[0] + "…"
        return text

    header_cells = [clean(header[i]) if i < len(header) else "" for i in keep]
    # Blank leading headers are almost always row-index columns.
    header_cells = [
        cell or ("#" if position == 0 else f"Detail {position}")
        for position, cell in enumerate(header_cells)
    ]

    rendered = ["| " + " | ".join(header_cells) + " |", "| " + " | ".join(["---"] * len(header_cells)) + " |"]

    for row in table[1:]:
        cells = [clean(row[i]) if i < len(row) else "" for i in keep]
        if not any(cells):
            continue
        joined = " ".join(cells)
        if _MEETING_CHATTER_RE.search(joined):
            continue
        rendered.append("| " + " | ".join(cells) + " |")

    return rendered if len(rendered) > 2 else []


def _parse_topic_narratives(raw: str) -> dict[int, str]:
    """Split an LLM batch response into per-topic narrative bodies."""
    if not raw or not raw.strip():
        return {}

    narratives: dict[int, str] = {}
    markers = list(re.finditer(r"(?im)^\s*(?:[-*]\s*)?\[\s*topic\s+(\d+)\s*\]\s*:?[ \t]*$", raw))
    for index, match in enumerate(markers):
        try:
            topic_number = int(match.group(1))
        except ValueError:
            continue
        start = match.end()
        end = markers[index + 1].start() if index + 1 < len(markers) else len(raw)
        body = raw[start:end].strip()
        body = re.sub(r"^#{1,6}\s.*$", "", body, flags=re.MULTILINE).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if len(body) >= 80:
            narratives[topic_number] = body
    return narratives


def _deterministic_topic_narrative(unit: _TopicUnit) -> str:
    """Summarise a topic strictly from its own captured content, with no invented detail."""
    facts = [line for line in unit.lines if len(line) >= 25][:14]
    subject = unit.title if unit.title else "this area of the programme"

    # Rotate phrasing so a long document does not read as a repeated template.
    variant = len(unit.title) % 3
    openers = (
        f"This section sets out {subject}.",
        f"The following material covers {subject}.",
        f"This topic documents {subject}.",
    )
    follow_ups = (
        "The supporting detail recorded for this topic is as follows.",
        "The associated particulars are recorded below.",
        "Further specifics captured for this topic are listed here.",
    )
    visual_only = (
        "The source material presents this topic through the accompanying visual and tabular material "
        "reproduced below rather than through narrative text.",
        "This topic is conveyed primarily by the figures and tables reproduced below.",
        "The content for this topic is carried by the accompanying exhibits reproduced below.",
    )

    paragraphs: list[str] = []

    if facts:
        paragraphs.append(f"{openers[variant]} " + " ".join(facts[:3]))
        if len(facts) > 3:
            paragraphs.append(f"{follow_ups[variant]} " + " ".join(facts[3:8]))
        if len(facts) > 8:
            paragraphs.append("Additional points captured for completeness include the following. " + " ".join(facts[8:14]))
    else:
        paragraphs.append(f"{openers[variant]} {visual_only[variant]}")

    if unit.tables:
        paragraphs.append(
            "The table below reproduces the structured values recorded for this topic so the figures and "
            "categories can be read directly."
        )

    if unit.images:
        paragraphs.append(
            "The figure accompanying this section reproduces the original visual, allowing the description "
            "above to be compared directly against the source material."
        )

    return "\n\n".join(paragraphs)


def _build_procedure_steps(units: list[_TopicUnit]) -> list[tuple[int, _TopicUnit]]:
    """Identify explicitly numbered process topics to drive the step-by-step section."""
    steps: list[tuple[int, _TopicUnit]] = []
    seen_numbers: set[int] = set()

    for unit in units:
        match = _STEP_TITLE_RE.match(unit.title)
        if not match:
            continue
        number = int(match.group(1))
        if number in seen_numbers or number > 30:
            continue
        seen_numbers.add(number)
        steps.append((number, unit))

    steps.sort(key=lambda item: item[0])
    return steps


# Instruction phrasing that must never end up in the published document title.
_PROMPT_INSTRUCTION_RE = re.compile(
    r"\b(please|describe|generate|create|make|give|produce|write|prepare|build|convert|"
    r"summari[sz]e|document|documentation|explain|provide|professional(ly)?|formal(ly)?|"
    r"detailed|comprehensive|full|complete|proper(ly)?|way|as\s+per|with\s+images?|"
    r"textbook|style|pdf|docx|word)\b",
    re.IGNORECASE,
)
_SLIDE_RANGE_RE = re.compile(
    r"\bslides?\s*\.?\s*\d+\s*(?:(?:-|–|—|to|through)\s*\d+)?\b",
    re.IGNORECASE,
)
_SOURCE_WORD_RE = re.compile(r"\b(ppt|pptx|deck|presentation|slides?|doc|file)\b", re.IGNORECASE)


def _clean_title_fragment(text: str) -> str:
    """Strip slide ranges, file-format words and filler punctuation from a candidate title."""
    cleaned = _SLIDE_RANGE_RE.sub(" ", text)
    cleaned = _SOURCE_WORD_RE.sub(" ", cleaned)
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip(" -–—,:;.\t")


def _looks_like_instruction(text: str) -> bool:
    """True when the text reads as a request to the tool rather than a subject name."""
    words = [word for word in re.findall(r"[A-Za-z]+", text)]
    if not words:
        return True
    instruction_hits = len(_PROMPT_INSTRUCTION_RE.findall(text))
    return instruction_hits >= 2 or (instruction_hits >= 1 and len(words) <= 4)


def _derive_document_title(
    req: ComposeRequest,
    slide_records: list,
    workspace_sources: list[str],
) -> str:
    """Build a professional document title from the subject matter, never from the raw prompt."""
    candidates: list[str] = []

    # The cover slide of a deck is normally the real document subject.
    for record in slide_records[:3]:
        title = getattr(record, "title", "") or ""
        if title:
            candidates.append(title)

    # The source filename is the next most reliable subject signal.
    for source in workspace_sources[:2]:
        candidates.append(Path(source).stem)

    # An explicit objective is usable when the author wrote a subject, not an instruction.
    if req.objective and req.objective.strip():
        candidates.append(req.objective.strip())

    for candidate in candidates:
        cleaned = _clean_title_fragment(candidate)
        if 3 <= len(cleaned) <= 90 and not _looks_like_instruction(cleaned):
            subject = cleaned[0].upper() + cleaned[1:]
            if re.search(r"\b(documentation|manual|handbook|guide|reference)\b", subject, re.IGNORECASE):
                return subject
            return f"{subject} — Technical Documentation"

    return "Technical Reference Documentation"


async def _generate_full_deck_document(
    req: ComposeRequest,
    slide_records: list,
    workspace_sources: list[str],
    batch_size: int = 3,
    max_concurrency: int = 4,
) -> str:
    """Produce a part-wise textbook-style manual with inline figures and tables."""
    units = _merge_slide_records_into_topics(slide_records)
    parts = _group_topics_into_parts(units)

    indexed_units = list(enumerate(units))
    unit_index = {id(unit): index for index, unit in indexed_units}
    narratives = await _render_topic_batches(
        req,
        indexed_units,
        batch_size=batch_size,
        max_concurrency=max_concurrency,
    )

    missing = [(index, unit) for index, unit in indexed_units if index not in narratives]
    if missing:
        repair_batch_size = 1 if len(missing) <= 6 else 2
        narratives.update(
            await _render_topic_batches(
                req,
                missing,
                batch_size=repair_batch_size,
                max_concurrency=max_concurrency,
                repair_mode=True,
            )
        )

    total_figures = sum(len(unit.images) for unit in units)
    total_tables = sum(len(unit.tables) for unit in units)
    steps = _build_procedure_steps(units)
    title = _derive_document_title(req, slide_records, workspace_sources)

    lines: list[str] = [f"# {title}", ""]

    lines.append("## Document Purpose and Scope")
    lines.append("")
    lines.append(
        "This document is a consolidated, publication-ready reference compiled from the approved source "
        f"material. The content is organised into {len(parts)} thematic parts covering {len(units)} distinct "
        f"topics, and reproduces {total_figures} supporting figures and {total_tables} data tables in the "
        "positions where they are referenced."
    )
    lines.append("")
    lines.append(
        "Related source material covering the same subject has been consolidated so each topic is presented "
        "once, in full, rather than repeated. Every statement is derived from the source material; no "
        "external assumptions have been added."
    )
    lines.append("")

    lines.append("## How This Document Is Organised")
    lines.append("")
    lines.append("| Part | Theme | Topics covered |")
    lines.append("| --- | --- | --- |")
    for position, (part_title, part_units) in enumerate(parts, start=1):
        lines.append(f"| Part {position} | {part_title} | {len(part_units)} |")
    lines.append("")

    if steps:
        lines.append("## Steps to Follow")
        lines.append("")
        lines.append(
            "The following sequence consolidates the end-to-end procedure described in the source material. "
            "Each step lists the actions recorded for that stage, followed by the supporting figure where one "
            "was provided."
        )
        lines.append("")
        for position, (_, unit) in enumerate(steps, start=1):
            step_title = _STEP_TITLE_RE.match(unit.title)
            clean_title = step_title.group(2).strip() if step_title else unit.title
            lines.append(f"### Step {position}: {clean_title}")
            lines.append("")
            for line in unit.lines[:8]:
                lines.append(f"- {line}")
            if unit.lines[:8]:
                lines.append("")
            for image in unit.images[:2]:
                lines.append(f"[[IMAGE:{image.image_name}]]")
                lines.append("")

    for position, (part_title, part_units) in enumerate(parts, start=1):
        lines.append(f"## Part {position}: {part_title}")
        lines.append("")
        lines.append(
            f"This part consolidates {len(part_units)} related topic(s) drawn from the source material and "
            "presents them as continuous reference documentation."
        )
        lines.append("")

        for unit in part_units:
            lines.append(f"### {unit.title}")
            lines.append("")

            narrative = narratives.get(unit_index[id(unit)]) or _deterministic_topic_narrative(unit)
            lines.append(narrative)
            lines.append("")

            for image in unit.images:
                lines.append(f"[[IMAGE:{image.image_name}]]")
                lines.append("")

            for table in unit.tables:
                rendered = _render_markdown_table(table)
                if rendered:
                    lines.extend(rendered)
                    lines.append("")

    lines.append("## Consolidated Summary")
    lines.append("")
    lines.append(
        "The preceding parts describe the programme objectives, the commercial and compliance prerequisites, "
        "the solution architecture, the environment configuration, and the governance and status controls "
        "required to operate and review the documented work."
    )
    lines.append("")
    lines.append("## Publication Readiness Considerations")
    lines.append("")
    lines.append("- Confirm figures, dates, and cost values against the latest approved source material.")
    lines.append("- Validate environment, security, and certificate details with the responsible platform owners.")
    lines.append("- Ensure the released version uses enterprise-approved wording and section ordering.")

    return "\n".join(lines).strip()


def _load_benchmark_snapshot() -> dict[str, object]:
    if not benchmark_report_path.exists():
        return {
            "status": "missing",
            "summary": {},
            "results": [],
            "updated_at": None,
        }

    payload = json.loads(benchmark_report_path.read_text(encoding="utf-8"))
    return {
        "status": "available",
        "summary": payload.get("summary", {}),
        "results": payload.get("results", []),
        "mode": payload.get("mode"),
        "updated_at": int(benchmark_report_path.stat().st_mtime),
    }


async def _generate_with_llm(prompt: str, model_override: str | None = None, images: list[str] | None = None) -> str:
    model_name = model_override or settings.llm_model
    cache_key = _cache_key_for_request(model_name, prompt, images)
    cached = _read_generation_cache(cache_key)
    if cached is not None:
        return cached

    if model_override == settings.vision_model and not await _model_available(model_name):
        raise HTTPException(status_code=502, detail=f"LLM model unavailable: {model_name}")

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
    }
    if images:
        payload["images"] = images

    try:
        llm_response = await app.state.http_client.post(f"{settings.llm_base_url}/api/generate", json=payload)
        llm_response.raise_for_status()
        data = llm_response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}") from exc

    optimized = data.get("response", "").strip()
    if not optimized:
        raise HTTPException(status_code=502, detail="LLM returned empty response")
    _write_generation_cache(
        cache_key,
        model_name=model_name,
        prompt=prompt,
        response=optimized,
        image_count=len(images or []),
    )
    return optimized


async def _extract_text_from_images(image_inputs: list[ImageInput]) -> list[str]:
    snippets: list[str] = []
    if not image_inputs:
        return snippets

    normalized_images: list[tuple[ImageInput, str]] = []
    for image in image_inputs:
        normalized = _normalize_base64(image.content_base64)
        try:
            base64.b64decode(normalized, validate=True)
        except binascii.Error as exc:
            raise HTTPException(status_code=400, detail=f"Invalid base64 image payload for {image.image_name}") from exc
        normalized_images.append((image, normalized))

    vision_model = await _resolve_vision_model()
    if vision_model is None:
        logger.info("vision_model_unavailable configured=%s candidates=%s", settings.vision_model, ", ".join(_vision_model_candidates()))
        return snippets

    for image, normalized in normalized_images:

        vision_prompt = (
            "Extract all readable text from the provided document image. "
            "Preserve section structure and bullet points when possible. "
            "Return plain text only."
        )
        try:
            extracted = await _generate_with_llm(
                prompt=vision_prompt,
                model_override=vision_model,
                images=[normalized],
            )
        except HTTPException as exc:
            if exc.status_code == 502:
                logger.info("vision_model_unavailable image=%s model=%s", image.image_name, vision_model)
                continue
            else:
                raise
        if not extracted.strip():
            extracted = "No readable text extracted."
        snippets.append(f"Image {image.image_name}:\n{extracted}")

    return snippets


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/capabilities")
async def capabilities() -> dict[str, object]:
    installed_models = sorted(await _installed_model_names())
    resolved_vision_model = await _resolve_vision_model()
    configured_text_available = settings.llm_model in installed_models
    configured_vision_available = settings.vision_model in installed_models

    return {
        "llm_base_url": settings.llm_base_url,
        "configured_text_model": settings.llm_model,
        "configured_vision_model": settings.vision_model,
        "vision_candidates": _vision_model_candidates(),
        "resolved_vision_model": resolved_vision_model,
        "installed_models": installed_models,
        "text_model_available": configured_text_available,
        "vision_model_available": configured_vision_available,
        "llm_cache_enabled": settings.llm_cache_enabled,
        "background_jobs_enabled": True,
    }


@app.get("/benchmarks")
def benchmarks() -> dict[str, object]:
    snapshot = _load_benchmark_snapshot()
    snapshot["rag_config"] = {
        "chunk_size_chars": settings.rag_chunk_size_chars,
        "chunk_overlap_chars": settings.rag_chunk_overlap_chars,
        "top_k_chunks": settings.rag_top_k_chunks,
        "use_embeddings": settings.rag_use_embeddings,
    }
    return snapshot


@app.get("/")
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


@app.post("/optimize", response_model=OptimizeResponse)
async def optimize(req: OptimizeRequest, ctx: RequestContext = Depends(get_request_context)) -> OptimizeResponse:
    text = enforce_input_limits(req.text, settings.max_input_chars)
    policy_flags = detect_policy_flags(text) if settings.enable_policy_guards else []

    if any(flag.startswith("disallowed_term:") for flag in policy_flags):
        raise HTTPException(status_code=400, detail={"error": "Policy violation", "flags": policy_flags})

    prompt = (
        "You are an enterprise document optimization assistant. "
        "Rewrite the document while preserving meaning, improving clarity, structure, and conciseness. "
        "Return only the optimized document text.\n\n"
        f"Objective: {req.objective}\n"
        f"Domain: {req.domain}\n"
        f"Source Document:\n{text}"
    )
    try:
        optimized = await _generate_with_llm(prompt)
    except HTTPException as exc:
        if exc.status_code == 502:
            optimized = req.text.strip()
            policy_flags.append("llm_fallback_used:optimize")
        else:
            raise

    return OptimizeResponse(
        document_id=req.document_id,
        optimized_text=optimized,
        policy_flags=policy_flags,
        model_used=settings.llm_model,
    )


async def _compose_document(req: ComposeRequest, ctx: RequestContext) -> ComposeResponse:
    stopwatch = Stopwatch()
    triage_before = image_triage.totals()
    profile = _generation_profile(req)
    raw_source = req.source_text.strip()
    workspace_context = ""
    workspace_sources: list[str] = []
    retrieval_stats: dict[str, int | float | bool] = {}
    workspace_image_inputs: list[ImageInput] = []
    relevant_workspace_files = []
    slide_records: list = []
    full_deck_mode = profile["mode"] == "full_deck"

    if req.use_workspace_context:
        relevant_workspace_files = select_workspace_files(
            workspace_root,
            _build_retrieval_query(req),
            req.workspace_file_hints,
            max_docs=int(profile["max_docs"]),
        )
        workspace_context, workspace_sources, retrieved_chunks, retrieved_stats = build_workspace_context(
            workspace_root=workspace_root,
            user_prompt=_build_retrieval_query(req),
            hints=req.workspace_file_hints,
            max_docs=int(profile["max_docs"]),
            max_chars_total=int(profile["max_chars_total"]),
            max_chars_per_doc=int(profile["max_chars_per_doc"]),
            chunk_size_chars=settings.rag_chunk_size_chars,
            chunk_overlap_chars=settings.rag_chunk_overlap_chars,
            top_k_chunks=int(profile["top_k_chunks"]),
            use_embeddings=settings.rag_use_embeddings,
        )
        retrieval_stats = {
            "candidate_files": retrieved_stats.candidate_files,
            "selected_files": retrieved_stats.selected_files,
            "chunks_scored": retrieved_stats.chunks_scored,
            "returned_chunks": retrieved_stats.returned_chunks,
            "cache_hits": retrieved_stats.cache_hits,
            "cache_misses": retrieved_stats.cache_misses,
            "context_chars": retrieved_stats.context_chars,
            "retrieval_latency_ms": retrieved_stats.retrieval_latency_ms,
            "top_score": retrieved_stats.top_score,
            "avg_top_score": retrieved_stats.avg_top_score,
            "used_embeddings": retrieved_stats.used_embeddings,
            "generation_mode": profile["mode"],
        }
        if full_deck_mode:
            for path in relevant_workspace_files:
                if path.suffix.lower() != ".pptx":
                    continue
                slide_records.extend(extract_pptx_slide_records(path))
            workspace_image_inputs = [image for record in slide_records for image in record.images]
        else:
            workspace_image_inputs = extract_workspace_images_from_paths(relevant_workspace_files)
    else:
        retrieved_chunks = []

    if full_deck_mode:
        all_image_inputs = _merge_image_inputs(req.image_inputs, workspace_image_inputs, max_total=240)
        image_text_snippets = await _extract_text_from_images(req.image_inputs)
    else:
        all_image_inputs = _merge_image_inputs(req.image_inputs, workspace_image_inputs)
        image_text_snippets = await _extract_text_from_images(all_image_inputs)
    image_context = "\n\n".join(image_text_snippets)

    effective_prompt, effective_objective, effective_instructions = _professional_authoring_brief(req, workspace_sources)
    instructions_text = "\n".join(f"- {item}" for item in effective_instructions if item.strip())
    extraction_latency_ms = stopwatch.lap_ms()

    seed_text = raw_source if raw_source else effective_prompt
    if image_context:
        seed_text = f"{seed_text}\n\nExtracted Image Text:\n{image_context}".strip()
    if workspace_context:
        seed_text = f"{seed_text}\n\nWorkspace Context:\n{workspace_context}".strip()
    seed_text = enforce_input_limits(seed_text, settings.max_input_chars)
    policy_flags = detect_policy_flags(seed_text) if settings.enable_policy_guards else []

    if any(flag.startswith("disallowed_term:") for flag in policy_flags):
        raise HTTPException(status_code=400, detail={"error": "Policy violation", "flags": policy_flags})

    prompt = (
        "You are an enterprise document optimization and authoring assistant. "
        "Produce clear, well-structured, publication-ready text based on the user request and instructions. "
        "Use professional headings and preserve broad source coverage. Do not over-compress important content. Return only final document content.\n\n"
        f"Objective: {effective_objective}\n"
        f"Domain: {req.domain}\n"
        f"Detail Level: {req.detail_level}\n"
        f"User Prompt:\n{effective_prompt}\n\n"
        f"Instructions:\n{instructions_text if instructions_text else '- None'}\n\n"
        f"Source Text:\n{seed_text}\n\n"
        f"Image Text Context:\n{image_context if image_context else '- None'}\n\n"
        f"Workspace Sources:\n{', '.join(workspace_sources) if workspace_sources else '- None'}\n\n"
        "Grounding Rule:\n"
        "Use retrieved workspace chunks as primary reference and keep content aligned to that style and structure."
    )

    try:
        if full_deck_mode and slide_records:
            optimized = await _generate_full_deck_document(
                req=req,
                slide_records=slide_records,
                workspace_sources=workspace_sources,
            )
        elif profile["mode"] == "dossier" and retrieved_chunks:
            optimized = await _generate_dossier_document(
                req=req,
                seed_text=seed_text,
                workspace_sources=workspace_sources,
                retrieved_chunks=retrieved_chunks,
                image_context=image_context,
                image_text_snippets=image_text_snippets,
            )
        elif profile["mode"] == "sectioned_comprehensive" and retrieved_chunks:
            optimized = await _generate_comprehensive_document(
                req=req,
                seed_text=seed_text,
                workspace_sources=workspace_sources,
                retrieved_chunks=retrieved_chunks,
                image_context=image_context,
            )
        else:
            optimized = await _generate_with_llm(prompt)
        optimized = _augment_short_output(optimized, req, retrieved_chunks, image_text_snippets)
        optimized, contract_rebuilt = _finalize_document_text(
            optimized,
            effective_prompt=effective_prompt,
            seed_text=seed_text,
            effective_instructions=effective_instructions,
            image_text_snippets=image_text_snippets,
            workspace_sources=workspace_sources,
            retrieved_chunks=retrieved_chunks,
            detail_level=req.detail_level,
        )
        if contract_rebuilt:
            policy_flags.append("document_contract_rewrite:compose")
    except HTTPException as exc:
        if exc.status_code == 502:
            optimized = _fallback_compose_text(
                user_prompt=effective_prompt,
                source_text=seed_text,
                instructions=effective_instructions,
                image_text_snippets=image_text_snippets,
                workspace_sources=workspace_sources,
                retrieved_chunks=retrieved_chunks,
                detail_level=req.detail_level,
            )
            optimized = _augment_short_output(optimized, req, retrieved_chunks, image_text_snippets)
            optimized, _ = _finalize_document_text(
                optimized,
                effective_prompt=effective_prompt,
                seed_text=seed_text,
                effective_instructions=effective_instructions,
                image_text_snippets=image_text_snippets,
                workspace_sources=workspace_sources,
                retrieved_chunks=retrieved_chunks,
                detail_level=req.detail_level,
            )
            policy_flags.append("llm_fallback_used:compose")
        else:
            raise
    generation_latency_ms = stopwatch.lap_ms()
    rendered = generate_artifacts(req.document_id, optimized, req.output_formats, image_inputs=all_image_inputs)
    if not rendered:
        raise HTTPException(status_code=400, detail="No valid output formats requested. Use pdf and/or docx.")
    render_latency_ms = stopwatch.lap_ms()
    artifacts = [
        save_artifact(
            owner_user_id=ctx.user_id,
            document_id=req.document_id,
            file_format=item.format,
            mime_type=item.mime_type,
            filename=item.filename,
            content=item.content,
            include_inline_artifact=req.include_inline_artifacts,
        )
        for item in rendered
    ]

    _record_compose_metrics(
        req=req,
        profile=profile,
        optimized=optimized,
        slide_records=slide_records,
        all_image_inputs=all_image_inputs,
        workspace_sources=workspace_sources,
        retrieval_stats=retrieval_stats,
        policy_flags=policy_flags,
        rendered=rendered,
        stopwatch=stopwatch,
        triage_before=triage_before,
        extraction_latency_ms=extraction_latency_ms,
        generation_latency_ms=generation_latency_ms,
        render_latency_ms=render_latency_ms,
    )

    return ComposeResponse(
        document_id=req.document_id,
        optimized_text=optimized,
        artifacts=artifacts,
        policy_flags=policy_flags,
        model_used=settings.llm_model,
        image_text_snippets=image_text_snippets,
        workspace_sources=workspace_sources,
        retrieval_chunks=[
            {
                "chunk_id": item.chunk_id,
                "source": item.source,
                "score": item.score,
                "preview": item.text[:180],
            }
            for item in retrieved_chunks
        ],
        retrieval_stats=retrieval_stats,
    )


@app.post("/compose", response_model=ComposeResponse)
async def compose(req: ComposeRequest, ctx: RequestContext = Depends(get_request_context)) -> ComposeResponse:
    return await _compose_document(req, ctx)


async def _run_compose_job(job_id: str, req: ComposeRequest, ctx: RequestContext) -> None:
    job = _compose_jobs[job_id]
    job["status"] = "running"
    job["updated_at"] = time.time()
    _persist_job_snapshot(job)

    try:
        result = await _compose_document(req, ctx)
        job["status"] = "completed"
        job["result"] = result.model_dump(mode="json")
        job["error"] = None
    except HTTPException as exc:
        job["status"] = "failed"
        job["error"] = str(exc.detail)
    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)
    finally:
        job["updated_at"] = time.time()
        job.pop("task", None)
        _persist_job_snapshot(job)


@app.post("/compose/jobs", status_code=202)
async def compose_async(req: ComposeRequest, ctx: RequestContext = Depends(get_request_context)) -> dict[str, object]:
    job_id = str(uuid4())
    created_at = time.time()
    job = {
        "job_id": job_id,
        "owner_user_id": ctx.user_id,
        "owner_user_role": ctx.user_role,
        "status": "queued",
        "created_at": created_at,
        "updated_at": created_at,
        "request": req.model_dump(mode="json"),
        "result": None,
        "error": None,
    }
    _compose_jobs[job_id] = job
    _persist_job_snapshot(job)
    job["task"] = asyncio.create_task(_run_compose_job(job_id, req, ctx))
    return _public_job_view(job)


@app.get("/compose/jobs/{job_id}")
async def compose_job_status(job_id: str, ctx: RequestContext = Depends(get_request_context)) -> dict[str, object]:
    job = _load_job_snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Compose job not found")
    _require_job_owner(job, ctx.user_id)
    return _public_job_view(job)


@app.get("/compose/jobs/{job_id}/result", response_model=ComposeResponse)
async def compose_job_result(job_id: str, ctx: RequestContext = Depends(get_request_context)) -> ComposeResponse:
    job = _load_job_snapshot(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Compose job not found")
    _require_job_owner(job, ctx.user_id)
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail={"status": job.get("status"), "error": job.get("error")})
    return ComposeResponse.model_validate(job.get("result") or {})


def _record_compose_metrics(
    *,
    req: ComposeRequest,
    profile: dict,
    optimized: str,
    slide_records: list,
    all_image_inputs: list,
    workspace_sources: list[str],
    retrieval_stats: dict,
    policy_flags: list[str],
    rendered: list,
    stopwatch: Stopwatch,
    triage_before: dict,
    extraction_latency_ms: float,
    generation_latency_ms: float,
    render_latency_ms: float,
) -> None:
    """Capture service-level KPIs for a completed run. Never raises."""
    try:
        structure = analyze_document(optimized)
        total_ms = stopwatch.total_ms()
        seconds = max(total_ms / 1000.0, 1e-6)
        figures_extracted = len(all_image_inputs)
        topics = int(structure["topics"])
        llm_topics, llm_coverage = estimate_llm_authorship(optimized, topics)

        breakdown = triage_delta(triage_before, image_triage.totals())
        suppressed = sum(count for key, count in breakdown.items() if key.startswith("dropped:"))
        kept = sum(count for key, count in breakdown.items() if key.startswith("kept:"))
        # Share of candidate assets that were judged worth publishing.
        visual_precision = round(kept / (kept + suppressed), 4) if (kept + suppressed) else 0.0

        metrics_registry.record(
            RunMetrics(
                document_id=req.document_id,
                generation_mode=str(profile.get("mode", req.detail_level)),
                succeeded=True,
                total_latency_ms=total_ms,
                extraction_latency_ms=extraction_latency_ms,
                generation_latency_ms=generation_latency_ms,
                render_latency_ms=render_latency_ms,
                slides_ingested=len(slide_records),
                slides_per_second=round(len(slide_records) / seconds, 3),
                output_chars=int(structure["output_chars"]),
                chars_per_second=round(int(structure["output_chars"]) / seconds, 2),
                parts=int(structure["parts"]),
                topics=topics,
                procedure_steps=int(structure["procedure_steps"]),
                tables_rendered=int(structure["tables_rendered"]),
                table_rows=int(structure["table_rows"]),
                figures_extracted=figures_extracted,
                figures_embedded=int(structure["figures_embedded"]),
                figure_retention_rate=(
                    round(int(structure["figures_embedded"]) / figures_extracted, 4)
                    if figures_extracted
                    else 0.0
                ),
                figures_suppressed=suppressed,
                triage_breakdown=breakdown,
                visual_precision_rate=visual_precision,
                llm_topics=llm_topics,
                llm_coverage_rate=llm_coverage,
                used_fallback=any("llm_fallback_used" in flag for flag in policy_flags),
                retrieval_top_score=float(retrieval_stats.get("top_score", 0.0) or 0.0),
                retrieval_latency_ms=float(retrieval_stats.get("retrieval_latency_ms", 0.0) or 0.0),
                grounding_sources=len(workspace_sources),
                leak_counts=dict(structure["leak_counts"]),
                content_integrity_pass=bool(structure["content_integrity_pass"]),
                artifact_bytes=sum(len(item.content) for item in rendered),
            )
        )
    except Exception:  # pragma: no cover - telemetry must not affect the request
        logger.debug("metrics capture skipped", exc_info=True)


@app.get("/metrics")
async def metrics(format: str = "json"):
    """Expose aggregated service-level KPIs for dashboards and scrapers."""
    if format.lower() == "prometheus":
        return PlainTextResponse(metrics_registry.prometheus())
    return metrics_registry.snapshot()


@app.get("/artifacts/{artifact_id}")
async def download_artifact(artifact_id: str, ctx: RequestContext = Depends(get_request_context)):
    meta = load_artifact(artifact_id)
    if ctx.user_role != "admin" and meta.owner_user_id != ctx.user_id:
        raise HTTPException(status_code=403, detail="You are not authorized to access this artifact")

    return FileResponse(path=meta.path, filename=meta.filename, media_type=meta.mime_type)
