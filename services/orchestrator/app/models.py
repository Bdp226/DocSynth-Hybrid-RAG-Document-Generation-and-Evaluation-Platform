from pydantic import BaseModel, Field


class OptimizeRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)
    objective: str = Field(default="Improve clarity, structure, and conciseness")
    domain: str = Field(default="general")


class OptimizeResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    document_id: str
    optimized_text: str
    policy_flags: list[str]
    model_used: str


class DocumentArtifact(BaseModel):
    artifact_id: str
    format: str
    filename: str
    mime_type: str
    content_base64: str = ""
    size_bytes: int
    download_path: str


class ImageInput(BaseModel):
    image_name: str = Field(..., min_length=1)
    mime_type: str = Field(..., min_length=1)
    content_base64: str = Field(..., min_length=1)


class ComposeRequest(BaseModel):
    document_id: str = Field(..., min_length=1)
    user_prompt: str = Field(..., min_length=1)
    source_text: str = Field(default="")
    instructions: list[str] = Field(default_factory=list)
    objective: str = Field(default="Optimize and produce publication-ready output")
    domain: str = Field(default="general")
    detail_level: str = Field(default="dossier", pattern="^(summary|standard|comprehensive|dossier|full_deck)$")
    output_formats: list[str] = Field(default_factory=lambda: ["pdf", "docx"])
    include_inline_artifacts: bool = Field(default=False)
    image_inputs: list[ImageInput] = Field(default_factory=list)
    use_workspace_context: bool = Field(default=True)
    workspace_file_hints: list[str] = Field(default_factory=list)
    max_workspace_docs: int = Field(default=5, ge=1, le=20)


class ComposeResponse(BaseModel):
    model_config = {"protected_namespaces": ()}

    document_id: str
    optimized_text: str
    artifacts: list[DocumentArtifact]
    policy_flags: list[str]
    model_used: str
    image_text_snippets: list[str] = Field(default_factory=list)
    workspace_sources: list[str] = Field(default_factory=list)
    retrieval_chunks: list[dict[str, str | float]] = Field(default_factory=list)
    retrieval_stats: dict[str, str | int | float | bool] = Field(default_factory=dict)
