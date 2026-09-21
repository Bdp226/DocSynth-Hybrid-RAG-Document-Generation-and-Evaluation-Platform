"""Measure duplicate content in a freshly composed document.

Runs one in-process compose (no browser, no cache reuse ambiguity) and reports
exactly which paragraphs, captions, headings and figures repeat.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main

client = TestClient(main.app)

PROMPT = (
    "Create a concise, publication-ready technical document based only on the provided "
    "source material. Remove duplicate figures, duplicate captions, repeated sentences, "
    "repeated tables and repeated boilerplate. Keep only unique, source-grounded content."
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _template_key(sentence: str) -> str:
    """Collapse a sentence to its opening phrase.

    Boilerplate such as "This section sets out <Title>." varies only in the subject,
    so exact-match counting reports it as unique. Keying on the leading words exposes
    the template and reveals how often the same sentence shape is emitted.
    """
    words = re.findall(r"[a-z0-9]+", _normalize(sentence))
    return " ".join(words[:5])


def main_check() -> None:
    response = client.post(
        "/compose",
        headers={"X-User-Id": "user-001", "X-User-Role": "author"},
        json={
            "document_id": "repetition-probe",
            "user_prompt": PROMPT,
            "objective": "Produce publication-ready reference documentation",
            "domain": "enterprise platform",
            "detail_level": "full_deck",
            "output_formats": ["pdf"],
            "include_inline_artifacts": False,
            "image_inputs": [],
            "workspace_file_hints": ["Sandbox environment.pptx"],
            "max_workspace_docs": 4,
        },
    )
    print(f"STATUS={response.status_code}")
    response.raise_for_status()
    payload = response.json()
    text = payload["optimized_text"]

    print(f"GENERATION_MODE={payload.get('retrieval_stats', {}).get('generation_mode')}")
    print(f"TEXT_CHARS={len(text)}")

    blocks = [block for block in text.split("\n\n") if block.strip()]
    headings = [line for line in text.splitlines() if line.startswith("#")]
    figures = re.findall(r"\[\[IMAGE:(.*?)\]\]", text)
    sentences = [
        sentence
        for block in blocks
        if not block.lstrip().startswith(("#", "|", "[[IMAGE:"))
        # An image token shares a block with its caption; it is markup, not prose.
        for sentence in re.split(r"(?<=[.!?])\s+", re.sub(r"\[\[IMAGE:.*?\]\]", " ", block))
        if len(sentence.strip()) >= 40
    ]

    for label, items in (
        ("PARAGRAPH", [_normalize(b) for b in blocks]),
        ("HEADING", [_normalize(h) for h in headings]),
        ("FIGURE", figures),
        ("SENTENCE", [_normalize(s) for s in sentences]),
    ):
        counts = Counter(items)
        repeats = {key: n for key, n in counts.items() if n > 1}
        extra = sum(n - 1 for n in repeats.values())
        print(f"{label}_TOTAL={len(items)} {label}_UNIQUE={len(counts)} {label}_DUPLICATE_EXTRA={extra}")
        for key, n in sorted(repeats.items(), key=lambda kv: -kv[1])[:5]:
            print(f"  {label}_REPEAT x{n}: {key[:140]}")

    template_counts = Counter(_template_key(s) for s in sentences if _template_key(s))
    template_repeats = {key: n for key, n in template_counts.items() if n > 2}
    template_extra = sum(n - 1 for n in template_repeats.values())
    print(
        f"TEMPLATE_TOTAL={len(sentences)} "
        f"TEMPLATE_SHAPES={len(template_counts)} "
        f"TEMPLATE_DUPLICATE_EXTRA={template_extra}"
    )
    for key, n in sorted(template_repeats.items(), key=lambda kv: -kv[1])[:8]:
        print(f"  TEMPLATE_REPEAT x{n}: {key}")


if __name__ == "__main__":
    main_check()
