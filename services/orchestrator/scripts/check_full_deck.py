"""Offline validation of the full-deck pipeline: slide extraction -> inline figures -> PDF."""

from __future__ import annotations

import asyncio
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from app.document_builder import generate_artifacts
from app.main import _generate_full_deck_document, _postprocess_document_text
from app.models import ComposeRequest
from app.workspace_context import extract_pptx_slide_records

DECK = Path(__file__).resolve().parents[3] / "Sandbox environment.pptx"


async def main() -> None:
    records = extract_pptx_slide_records(DECK)
    total_images = sum(len(r.images) for r in records)
    print(f"SLIDES={len(records)} IMAGES={total_images}")

    req = ComposeRequest(
        document_id="full-deck-check",
        user_prompt="Sandbox Environment Reference Manual",
        detail_level="full_deck",
        output_formats=["pdf"],
    )

    # Force the deterministic path so we measure the guaranteed floor (no LLM).
    text = await _generate_full_deck_document(
        req=req,
        slide_records=records,
        workspace_sources=[DECK.name],
        batch_size=10_000,
        max_concurrency=1,
    )
    text = _postprocess_document_text(text)
    print(f"TEXT_CHARS={len(text)}")
    print(f"IMAGE_TOKENS={text.count('[[IMAGE:')}")

    images = [image for record in records for image in record.images]
    artifacts = generate_artifacts(req.document_id, text, ["pdf"], image_inputs=images)
    pdf_bytes = next(a for a in artifacts if a.format == "pdf").content

    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = len(reader.pages)
    pages_with_images = sum(1 for page in reader.pages if page.images)
    embedded = sum(len(page.images) for page in reader.pages)
    first_image_page = next((i + 1 for i, p in enumerate(reader.pages) if p.images), None)
    last_image_page = next((len(reader.pages) - i for i, p in enumerate(reversed(reader.pages)) if p.images), None)

    out_dir = Path(__file__).resolve().parents[1] / "build"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "full_deck_check.pdf"
    out.write_bytes(pdf_bytes)

    print(f"PAGES={pages}")
    print(f"PAGES_WITH_IMAGES={pages_with_images}")
    print(f"EMBEDDED_IMAGES={embedded}")
    print(f"FIRST_IMAGE_PAGE={first_image_page} LAST_IMAGE_PAGE={last_image_page}")
    print(f"PDF={out}")


if __name__ == "__main__":
    asyncio.run(main())
