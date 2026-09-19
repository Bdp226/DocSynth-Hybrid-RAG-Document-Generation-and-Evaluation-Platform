"""Find which post-processing rule removes generated narrative lines."""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SAMPLE = [
    "This document is a consolidated, publication-ready reference compiled from the approved source "
    "material. The content is organised into 8 thematic parts covering 98 distinct topics, and "
    "reproduces 79 supporting figures and 46 data tables in the positions where they are explained.",
    "Related source material covering the same subject has been consolidated so each topic is presented "
    "once, in full, rather than repeated. Every statement is derived from the source material; no "
    "external assumptions have been introduced.",
    "This part consolidates 12 related topic(s) drawn from the source material and presents them as "
    "continuous reference documentation.",
]

RULES = {
    "source_chunk": lambda line: re.match(r"^Source Chunk:\s*", line, re.IGNORECASE),
    "slide_marker": lambda line: re.match(r"^\[Slide\s+\d+\]$", line, re.IGNORECASE),
    "author_dept": lambda line: re.match(r"^Author\s*\|\s*Department$", line, re.IGNORECASE),
    "shift_ise": lambda line: re.match(r"^SHIFT\s+ISE\s+India$", line, re.IGNORECASE),
    "plan_to_do": lambda line: re.match(r"^What\s+we\s+plan\s+to\s+do\??$", line, re.IGNORECASE),
    "chatter": lambda line: re.search(
        r"\b(discussed|introduced|asked|explained|mentioned|looping in)\b", line, re.IGNORECASE
    ),
    "name_list": lambda line: re.search(r"(?:\b[A-Z][a-z]+\b,\s*){2,}\b(?:and\s+)?[A-Z][a-z]+\b", line),
    "x_days": lambda line: re.search(r"\b[A-Z]\s+Days\b", line),
    "many_q": lambda line: line.count("?") >= 2,
}

for text in SAMPLE:
    hits = [name for name, rule in RULES.items() if rule(text)]
    print(f"DROPPED_BY={hits or 'NONE'}")
    print(f"   {text[:110]}...")
    for name in hits:
        match = RULES[name](text)
        if hasattr(match, "group"):
            print(f"   rule '{name}' matched: {match.group(0)!r}")
    print()
