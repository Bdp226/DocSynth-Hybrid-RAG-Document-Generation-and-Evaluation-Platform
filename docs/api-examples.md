# API Examples

## 0) UI usage

Open the control center UI in browser:

`http://localhost:8080/ui/`

Use the UI for:
- Optimize Existing Text mode
- Compose + Generate Files mode
- Multi-user identity headers for enterprise testing

## 1) Optimize existing content

```bash
curl -X POST http://localhost:8080/optimize \
  -H "X-User-Id: user-001" \\
  -H "X-User-Role: author" \\
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "policy-note-01",
    "text": "The current paragraph is unclear and repetitive...",
    "objective": "Improve clarity and reduce verbosity",
    "domain": "operations"
  }'
```

## 2) Compose + generate PDF and DOCX

```bash
curl -X POST http://localhost:8080/compose \
  -H "X-User-Id: user-001" \\
  -H "X-User-Role: author" \\
  -H "Content-Type: application/json" \
  -d '{
    "document_id": "release-summary-q3",
    "user_prompt": "Create a one-page executive summary of the Q3 release outcomes.",
    "source_text": "",
    "instructions": [
      "Use crisp headers",
      "Keep total length under 500 words",
      "Include risk and mitigation section"
    ],
    "objective": "Executive-ready summary",
    "domain": "program-management",
    "output_formats": ["pdf", "docx"],
    "include_inline_artifacts": false,
    "use_workspace_context": true,
    "workspace_file_hints": [
      "Sandbox environment.pptx",
      "SHIFT_Sandbox_Documentation_Slides_81-141 (1).pdf"
    ],
    "image_inputs": [
      {
        "image_name": "meeting-notes.png",
        "mime_type": "image/png",
        "content_base64": "data:image/png;base64,<base64-image-content>"
      }
    ]
  }'
```

Response includes:
- `optimized_text`
- `artifacts[]` with `artifact_id`, `download_path`, `format`, `filename`, `mime_type`, `size_bytes`
- `image_text_snippets[]` showing extracted text used during composition
- `workspace_sources[]` showing workspace docs used for grounding
- `retrieval_chunks[]` showing top-ranked chunks with scores and previews
- `policy_flags` and `model_used`

## 3) Decode returned artifact

Download the artifact with the same user identity headers:

```bash
curl -X GET http://localhost:8080/artifacts/<artifact_id> \
  -H "X-User-Id: user-001" \
  -H "X-User-Role: author" \
  --output generated.docx
```

If `include_inline_artifacts=true` is requested, `content_base64` is returned as well.
