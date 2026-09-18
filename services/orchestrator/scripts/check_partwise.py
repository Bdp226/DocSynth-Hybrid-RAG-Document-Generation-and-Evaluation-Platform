"""Measure the restructured part-wise document: structure, tables, figures, and leakage checks."""
from __future__ import annotations

import asyncio
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from app.document_builder import generate_artifacts
from app.main import _generate_full_deck_document, _postprocess_document_text
from app.models import ComposeRequest
from app.workspace_context import extract_pptx_slide_records

DECK = Path(__file__).resolve().parents[3] / "Sandbox environment.pptx"

LEAK_PATTERNS = {
    "slide_reference": re.compile(r"\bslide\s+\d+\b", re.IGNORECASE),
    "roster_roles": re.compile(r"\((?:Founder|Eng\.?\s*Head|DEV|PO|AR|PL\s*&\s*SM)\)", re.IGNORECASE),
    # Real chatter is a named participant plus a reporting verb.
    "meeting_chatter": re.compile(
        r"\blooping\s+in\b"
        r"|\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\s+(?:has\s+|have\s+|had\s+)?"
        r"(?:discussed|introduced|asked|explained|mentioned)\b"
    ),
    "raw_bold_marker": re.compile(r"\*\*"),
}


async def main() -> None:
    records = extract_pptx_slide_records(DECK)
    print(f"SLIDES={len(records)}")

    req = ComposeRequest(
        document_id="partwise-check",
        user_prompt="Sandbox Environment Reference Manual",
        detail_level="full_deck",
        output_formats=["pdf"],
    )

    # batch_size huge => no LLM batching benefit; we measure the deterministic floor.
    text = await _generate_full_deck_document(
        req=req,
        slide_records=records,
        workspace_sources=[DECK.name],
        batch_size=10_000,
        max_concurrency=1,
    )
    text = _postprocess_document_text(text)

    parts = re.findall(r"^## Part \d+: (.+)$", text, flags=re.MULTILINE)
    topics = re.findall(r"^### (.+)$", text, flags=re.MULTILINE)
    steps = re.findall(r"^### Step \d+: (.+)$", text, flags=re.MULTILINE)
    table_rows = [line for line in text.splitlines() if line.startswith("|")]

    print(f"TEXT_CHARS={len(text)}")
    print(f"PARTS={len(parts)}")
    for part in parts:
        print(f"   - {part}")
    print(f"TOPICS={len(topics)}  STEPS={len(steps)}")
    print(f"TABLE_ROWS={len(table_rows)}")
    print(f"IMAGE_TOKENS={text.count('[[IMAGE:')}")
    print(f"HAS_STEPS_SECTION={'## Steps to Follow' in text}")

    print("--- LEAK CHECKS (markdown, excluding internal image tokens) ---")
    text_without_tokens = re.sub(r"^\[\[IMAGE:.+?\]\]$", "", text, flags=re.MULTILINE)
    for name, pattern in LEAK_PATTERNS.items():
        hits = pattern.findall(text_without_tokens)
        print(f"{name}={len(hits)}")
        if hits:
            match = re.search(pattern, text_without_tokens)
            start = max(0, match.start() - 70)
            print(f"    ...{text_without_tokens[start:match.end() + 70]}...")

    images = [image for record in records for image in record.images]
    artifacts = generate_artifacts(req.document_id, text, ["pdf"], image_inputs=images)
    pdf_bytes = next(a for a in artifacts if a.format == "pdf").content
    reader = PdfReader(io.BytesIO(pdf_bytes))
    out_dir = Path(__file__).resolve().parents[1] / "build"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / "partwise_check.pdf"
    out.write_bytes(pdf_bytes)

    rendered = "\n".join((page.extract_text() or "") for page in reader.pages)
    print("--- LEAK CHECKS (rendered PDF text) ---")
    for name, pattern in LEAK_PATTERNS.items():
        hits = pattern.findall(rendered)
        print(f"rendered_{name}={len(hits)}")
        if hits:
            match = re.search(pattern, rendered)
            start = max(0, match.start() - 70)
            print(f"    ...{rendered[start:match.end() + 70]}...")

    print(f"RENDERED_FIGURE_CAPTIONS={len(re.findall(r'Figure \d+', rendered))}")
    print(f"PDF_PAGES={len(reader.pages)}")
    print(f"PDF_PAGES_WITH_IMAGES={sum(1 for p in reader.pages if p.images)}")
    print(f"PDF_EMBEDDED_IMAGES={sum(len(p.images) for p in reader.pages)}")
    print(f"PDF={out}")


if __name__ == "__main__":
    asyncio.run(main())
