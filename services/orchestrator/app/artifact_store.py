from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from .config import settings
from .models import DocumentArtifact


@dataclass
class StoredArtifactMeta:
    artifact_id: str
    owner_user_id: str
    format: str
    mime_type: str
    filename: str
    path: str
    size_bytes: int


def _store_root() -> Path:
    root = Path(settings.artifact_storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _meta_path(artifact_id: str) -> Path:
    return _store_root() / f"{artifact_id}.json"


def save_artifact(
    owner_user_id: str,
    document_id: str,
    file_format: str,
    mime_type: str,
    filename: str,
    content: bytes,
    include_inline_artifact: bool,
) -> DocumentArtifact:
    artifact_id = str(uuid4())
    safe_name = f"{document_id}_{artifact_id}.{file_format}"
    file_path = _store_root() / safe_name
    file_path.write_bytes(content)

    meta = StoredArtifactMeta(
        artifact_id=artifact_id,
        owner_user_id=owner_user_id,
        format=file_format,
        mime_type=mime_type,
        filename=filename,
        path=str(file_path),
        size_bytes=len(content),
    )
    _meta_path(artifact_id).write_text(json.dumps(meta.__dict__), encoding="utf-8")

    return DocumentArtifact(
        artifact_id=artifact_id,
        format=file_format,
        filename=filename,
        mime_type=mime_type,
        content_base64="" if not include_inline_artifact else base64.b64encode(content).decode("ascii"),
        size_bytes=len(content),
        download_path=f"/artifacts/{artifact_id}",
    )


def load_artifact(artifact_id: str) -> StoredArtifactMeta:
    meta_file = _meta_path(artifact_id)
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")

    meta_data = json.loads(meta_file.read_text(encoding="utf-8"))
    return StoredArtifactMeta(**meta_data)
