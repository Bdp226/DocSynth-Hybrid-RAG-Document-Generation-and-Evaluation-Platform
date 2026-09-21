import base64
import io
import json
import re
import urllib.request
from pathlib import Path

from pypdf import PdfReader

payload = {
    "document_id": "roundtrip-20260921-check",
    "user_prompt": "Create a concise, publication-ready technical document based only on the provided source material. Remove duplicate figures, duplicate captions, repeated sentences, repeated tables and repeated boilerplate. Keep only unique, source-grounded content.",
    "objective": "Produce publication-ready reference documentation",
    "domain": "enterprise platform",
    "detail_level": "full_deck",
    "output_formats": ["pdf"],
    "include_inline_artifacts": True,
    "workspace_file_hints": ["Sandbox environment.pptx"],
    "max_workspace_docs": 4,
}

req = urllib.request.Request(
    "http://127.0.0.1:8080/compose",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "X-User-Id": "user-001",
        "X-User-Role": "author",
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=600) as resp:
    body = resp.read().decode("utf-8")

obj = json.loads(body)
text = obj.get("optimized_text", "")
print("OPT_HAS_EMDASH_CAPTION=", bool(re.search(r"Figure\s+\d+\s*[—-]", text)))
print("OPT_PERIOD_CAPTIONS=", len(re.findall(r"Figure\s+\d+\.\s", text)))
print("OPT_EMDASH_CAPTIONS=", len(re.findall(r"Figure\s+\d+\s*[—-]", text)))

artifacts = obj.get("artifacts", [])
pdf = next((a for a in artifacts if a.get("format") == "pdf"), None)
if not pdf or not pdf.get("content_base64"):
    print("NO_INLINE_PDF")
    raise SystemExit(0)

raw = base64.b64decode(pdf["content_base64"])
out = Path.home() / "Downloads" / "roundtrip-check.pdf"
out.write_bytes(raw)
print("SAVED=", out)

pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
print("PDF_HAS_EMDASH_CAPTION=", bool(re.search(r"Figure\s+\d+\s*[—-]", pdf_text)))
print("PDF_PERIOD_CAPTIONS=", len(re.findall(r"Figure\s+\d+\.\s", pdf_text)))
print("PDF_EMDASH_CAPTIONS=", len(re.findall(r"Figure\s+\d+\s*[—-]", pdf_text)))
print("PDF_APPENDIX_COUNT=", len(re.findall(r"Appendix Figure\s+\d+", pdf_text)))
