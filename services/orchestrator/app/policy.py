from __future__ import annotations

import re


PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "phone": re.compile(r"\+?[0-9][0-9\-\s]{7,}[0-9]"),
}


DISALLOWED_TERMS = {
    "public_release_unapproved",
    "send_external_raw_data",
}


def detect_policy_flags(text: str) -> list[str]:
    flags: list[str] = []

    for key, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            flags.append(f"pii_detected:{key}")

    lower_text = text.lower()
    for term in DISALLOWED_TERMS:
        if term in lower_text:
            flags.append(f"disallowed_term:{term}")

    return flags


def enforce_input_limits(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars]
