import base64
import io
import json
import re
import urllib.request
from pathlib import Path

from pypdf import PdfReader


doc_id = "fastfix-8090"
payload = {
    "document_id": doc_id,
    "user_prompt": (
        "Create a concise, publication-ready technical document based only on the provided "
        "source material. Remove duplicate figures, duplicate captions, repeated sentences, "
        "repeated tables and repeated boilerplate. Keep only unique, source-grounded content."
    ),
    "objective": "Produce publication-ready reference documentation",
    "domain": "enterprise platform",
    "detail_level": "full_deck",
    "output_formats": ["pdf"],
    "include_inline_artifacts": True,
    "workspace_file_hints": ["Sandbox environment.pptx"],
    "max_workspace_docs": 4,
}

req = urllib.request.Request(
    "http://127.0.0.1:8090/compose",
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Content-Type": "application/json",
        "X-User-Id": "user-001",
        "X-User-Role": "author",
    },
    method="POST",
)

with urllib.request.urlopen(req, timeout=600) as resp:
    obj = json.loads(resp.read().decode("utf-8"))

text = obj.get("optimized_text", "")
pdf = next((a for a in (obj.get("artifacts") or []) if a.get("format") == "pdf"), None)
raw = base64.b64decode(pdf["content_base64"])
out = Path.home() / "Downloads" / "fastfix-8090.pdf"
out.write_bytes(raw)

pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)

print("SAVED=", out)
print("OPT_EMDASH=", len(re.findall(r"Figure\s+\d+\s*[—-]", text)))
print("PDF_EMDASH=", len(re.findall(r"Figure\s+\d+\s*[—-]", pdf_text)))
print("PDF_PERIOD=", len(re.findall(r"Figure\s+\d+\.\s", pdf_text)))
print("PDF_APPENDIX=", len(re.findall(r"Appendix Figure\s+\d+", pdf_text)))
