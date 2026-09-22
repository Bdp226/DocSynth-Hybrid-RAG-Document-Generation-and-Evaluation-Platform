import argparse
import base64
import json
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.error import URLError

from pypdf import PdfReader


def compose_request(port: int, payload: dict) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, 4):
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
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (ConnectionError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 3:
                break
            wait_s = 2 * attempt
            print(f"[WARN] compose attempt {attempt} failed: {exc}. Retrying in {wait_s}s...")
            time.sleep(wait_s)

    raise RuntimeError(f"Compose failed after retries: {last_error}")


def check_runtime_signature(port: int) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/debug/render-signature",
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def save_artifacts(doc_id: str, artifacts: list[dict], output_dir: Path) -> list[Path]:
    saved: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for artifact in artifacts or []:
        fmt = (artifact.get("format") or "").lower()
        b64 = artifact.get("content_base64")
        if not fmt or not b64:
            continue
        raw = base64.b64decode(b64)
        path = output_dir / f"{doc_id}.{fmt}"
        path.write_bytes(raw)
        saved.append(path)

    return saved


def pdf_metrics(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return {
        "pages": len(reader.pages),
        "period_captions": len(re.findall(r"Figure\s+\d+\.\s", text)),
        "emdash_captions": len(re.findall(r"Figure\s+\d+\s*[—-]", text)),
        "appendix_count": len(re.findall(r"Appendix Figure\s+\d+", text)),
        "overflow_note_present": (
            "supporting screenshot(s) are held in the source material and are not reproduced here." in text
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate document from the same PPT with fresh doc ID and save artifacts."
    )
    parser.add_argument("--port", type=int, default=8090, help="Compose API port (default: 8090)")
    parser.add_argument(
        "--source-ppt",
        default="Sandbox environment.pptx",
        help="Source PPT filename already present in workspace/doc hints",
    )
    parser.add_argument(
        "--output-dir",
        default=str(Path.home() / "Downloads"),
        help="Folder to save generated files",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["pdf"],
        choices=["pdf", "docx"],
        help="Output formats to request",
    )
    parser.add_argument(
        "--skip-runtime-check",
        action="store_true",
        help="Skip /debug/render-signature preflight validation",
    )
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

    if not args.skip_runtime_check:
        signature = check_runtime_signature(args.port)
        print(f"[INFO] Runtime signature: {signature}")
        critical_ok = signature.get("pdf_has_autocaption_call") is False
        if not critical_ok:
            raise RuntimeError(
                "Runtime on selected port is stale (renderer signature mismatch). "
                "Restart server on this port with latest code, then rerun script."
            )
        if not signature.get("pdf_uses_appendix_slice"):
            print("[WARN] Runtime signature indicates appendix-slice marker not detected; continuing.")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    doc_id = f"fastfix-{ts}"

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
        "output_formats": args.formats,
        "include_inline_artifacts": True,
        "workspace_file_hints": [source_hint],
        "max_workspace_docs": 1,
    }

    print(f"[INFO] Sending compose request to port {args.port} with doc_id={doc_id}")
    result = compose_request(args.port, payload)

    output_dir = Path(args.output_dir)
    saved = save_artifacts(doc_id, result.get("artifacts") or [], output_dir)

    if not saved:
        raise RuntimeError("No artifacts returned by API.")

    print("[INFO] Saved files:")
    for path in saved:
        print(f"  - {path}")

    optimized_text = result.get("optimized_text") or ""
    print(f"[CHECK] OPT_EMDASH={len(re.findall(r'Figure\\s+\\d+\\s*[—-]', optimized_text))}")

    pdf_path = next((p for p in saved if p.suffix.lower() == ".pdf"), None)
    if pdf_path is not None:
        metrics = pdf_metrics(pdf_path)
        print(f"[CHECK] PDF_PAGES={metrics['pages']}")
        print(f"[CHECK] PDF_PERIOD_CAPTIONS={metrics['period_captions']}")
        print(f"[CHECK] PDF_EMDASH_CAPTIONS={metrics['emdash_captions']}")
        print(f"[CHECK] PDF_APPENDIX_COUNT={metrics['appendix_count']}")
        print(f"[CHECK] PDF_OVERFLOW_NOTE_PRESENT={metrics['overflow_note_present']}")

    print("[DONE] Regeneration completed.")


if __name__ == "__main__":
    main()
