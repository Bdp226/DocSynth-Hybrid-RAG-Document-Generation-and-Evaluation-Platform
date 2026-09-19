from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main

client = TestClient(main.app)


def _headers() -> dict[str, str]:
    return {
        "X-User-Id": "user-001",
        "X-User-Role": "author",
    }


def main_check() -> None:
    response = client.post(
        "/compose",
        headers=_headers(),
        json={
            "document_id": "live-full-deck",
            "user_prompt": "Describe in professional way the full doc as per ppt slides and give from slide 81-144 and with images",
            "objective": "Produce complete publication-ready reference documentation from the deck",
            "domain": "enterprise platform",
            "detail_level": "full_deck",
            "output_formats": ["pdf"],
            "include_inline_artifacts": True,
            "image_inputs": [],
            "workspace_file_hints": ["Sandbox environment.pptx"],
            "max_workspace_docs": 4,
        },
    )
    print(f"STATUS={response.status_code}")
    response.raise_for_status()
    payload = response.json()

    text = payload["optimized_text"]
    print(f"TEXT_CHARS={len(text)}")
    print(f"IMAGE_SNIPPETS={len(payload.get('image_text_snippets', []))}")
    print(f"RETRIEVAL_MODE={payload.get('retrieval_stats', {}).get('generation_mode')}")
    print(f"WORKSPACE_SOURCES={','.join(payload.get('workspace_sources', []))}")
    print(f"RETRIEVAL_DOCS={payload.get('retrieval_stats', {}).get('documents_considered')}")
    print(f"IMAGE_TOKENS={text.count('[[IMAGE:')}")
    print("TEXT_HEAD=" + text[:500].replace("\n", " "))

    artifact = next(item for item in payload["artifacts"] if item["format"] == "pdf")
    pdf_bytes = base64.b64decode(artifact["content_base64"])
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = len(reader.pages)
    pages_with_images = sum(1 for page in reader.pages if page.images)
    embedded_images = sum(len(page.images) for page in reader.pages)
    first_image_page = next((index + 1 for index, page in enumerate(reader.pages) if page.images), None)
    last_image_page = next(
        (len(reader.pages) - index for index, page in enumerate(reversed(reader.pages)) if page.images), None
    )

    out_dir = Path(__file__).resolve().parents[1] / "build"
    out_dir.mkdir(exist_ok=True)
    output_path = out_dir / "live_full_deck_compose.pdf"
    output_path.write_bytes(pdf_bytes)

    print(f"PDF_PAGES={pages}")
    print(f"PDF_PAGES_WITH_IMAGES={pages_with_images}")
    print(f"PDF_EMBEDDED_IMAGES={embedded_images}")
    print(f"PDF_FIRST_IMAGE_PAGE={first_image_page}")
    print(f"PDF_LAST_IMAGE_PAGE={last_image_page}")
    print(f"PDF_PATH={output_path}")


if __name__ == "__main__":
    main_check()
