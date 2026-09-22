import argparse
import base64
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader


def compose(port: int, payload: dict) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/compose",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-User-Id": "user-001",
            "X-User-Role": "author",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=900) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_pdf(doc_id: str, artifacts: list[dict], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = next((a for a in (artifacts or []) if (a.get("format") or "").lower() == "pdf"), None)
    if not pdf or not pdf.get("content_base64"):
        raise RuntimeError("No PDF artifact in response")
    raw = base64.b64decode(pdf["content_base64"])
    path = out_dir / f"{doc_id}.pdf"
    path.write_bytes(raw)
    return path


def normalize(line: str) -> str:
    text = re.sub(r"\b(\d{1,3})\s+(st|nd|rd|th)\b", r"\1\2", line, flags=re.IGNORECASE)
    text = re.sub(r"[^0-9a-z]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def get_pdf_lines(pdf_path: Path) -> tuple[list[str], str]:
    reader = PdfReader(str(pdf_path))
    pages = [page.extract_text() or "" for page in reader.pages]
    all_text = "\n".join(pages)
    lines = [ln.strip() for ln in all_text.splitlines() if ln.strip()]
    return lines, all_text


def find_keyword_pages(pdf_path: Path, keywords: list[str]) -> dict[str, list[int]]:
    reader = PdfReader(str(pdf_path))
    result: dict[str, list[int]] = {k: [] for k in keywords}
    for i, page in enumerate(reader.pages, start=1):
        txt = (page.extract_text() or "").casefold()
        for k in keywords:
            if k.casefold() in txt:
                result[k].append(i)
    return result


def repeated_status_heading_check(lines: list[str]) -> list[str]:
    issues: list[str] = []
    for i in range(len(lines) - 1):
        a = normalize(lines[i])
        b = normalize(lines[i + 1])
        if a.startswith("status as of") and b.startswith("status as of") and a == b:
            issues.append(f"Repeated status heading lines at line indexes {i} and {i+1}: '{lines[i]}'")
    return issues


def local_mix_check(lines: list[str]) -> list[str]:
    issues: list[str] = []

    heading_re = re.compile(r"^\d{1,3}\.\s+(.+)$")
    figure_re = re.compile(r"^Figure\s+\d+\.\s+(.+)$")
    current_heading = ""

    for line in lines:
        heading_match = heading_re.match(line)
        if heading_match:
            current_heading = heading_match.group(1).strip()
            continue

        figure_match = figure_re.match(line)
        if not figure_match or not current_heading:
            continue

        figure_subject = figure_match.group(1).strip()
        if figure_subject.casefold().startswith("continuation view"):
            continue

        heading_key = normalize(current_heading)
        figure_key = normalize(figure_subject)
        if not heading_key or not figure_key:
            continue

        heading_tokens = set(heading_key.split())
        figure_tokens = set(figure_key.split())
        overlap = len(heading_tokens & figure_tokens)
        union = len(heading_tokens | figure_tokens) or 1
        similarity = overlap / union

        if heading_key in figure_key or figure_key in heading_key or similarity >= 0.35:
            continue

        issues.append(
            "Potential mix: figure caption subject does not align with the active section heading "
            f"(section='{current_heading}', figure='{figure_subject}')."
        )

    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Regenerate from PPT and run strict PDF QC checks.")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--source-ppt", default="Sandbox environment.pptx")
    parser.add_argument("--output-dir", default=str(Path.home() / "Downloads"))
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[3]
    source_candidate = Path(args.source_ppt)
    source_hint = args.source_ppt
    if source_candidate.is_absolute() and source_candidate.exists():
        source_hint = str(source_candidate)
    else:
        repo_candidate = repo_root / args.source_ppt
        if repo_candidate.exists():
            source_hint = str(repo_candidate)

    doc_id = f"strictfix-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
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
        "workspace_file_hints": [source_hint],
        "max_workspace_docs": 1,
    }

    print(f"[INFO] Compose start on port {args.port} with doc_id={doc_id}")
    result = compose(args.port, payload)

    out_path = save_pdf(doc_id, result.get("artifacts") or [], Path(args.output_dir))
    print(f"[INFO] PDF saved: {out_path}")

    optimized_text = result.get("optimized_text") or ""
    print(f"[CHECK] OPT_EMDASH={len(re.findall(r'Figure\s+\d+\s*[—-]', optimized_text))}")

    lines, all_text = get_pdf_lines(out_path)
    print(f"[CHECK] PDF_PERIOD_CAPTIONS={len(re.findall(r'Figure\s+\d+\.\s', all_text))}")
    print(f"[CHECK] PDF_EMDASH_CAPTIONS={len(re.findall(r'Figure\s+\d+\s*[—-]', all_text))}")
    print(f"[CHECK] PDF_APPENDIX_COUNT={len(re.findall(r'Appendix Figure\s+\d+', all_text))}")

    pages = find_keyword_pages(
        out_path,
        [
            "Azure Cost Analysis",
            "Setting Custom Range",
            "Requesting OpenAI API Keys",
            "Creation of A01 accts",
        ],
    )
    for k, v in pages.items():
        print(f"[PAGES] {k}: {v}")

    issues = []
    issues.extend(repeated_status_heading_check(lines))
    issues.extend(local_mix_check(lines))

    if issues:
        print("[QC] FAIL")
        for item in issues:
            print(f"  - {item}")
        raise SystemExit(2)

    print("[QC] PASS")
    print("[DONE] Regeneration + strict checks completed.")


if __name__ == "__main__":
    main()
