from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "doc_optimizer"
SERVICE_VERSION = "0.1.0"


class Settings(BaseSettings):
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080
    git_commit: str = "unknown"
    # Set by the container build (Dockerfile ARG/ENV BUILD_TIME); "unknown" for local runs.
    build_time: str = "unknown"
    rate_limit_requests_per_minute: int = 120
    rate_limit_burst: int = 30
    rate_limit_exempt_paths: str = "/healthz,/readyz,/health,/version,/metrics"
    rate_limit_exempt_path_set: set[str] = {"/healthz", "/readyz", "/health", "/version", "/metrics"}
    max_request_bytes: int = 25000000
    cors_enabled: bool = False
    cors_origin_list: list[str] = []
    readiness_requires_llm: bool = False

    llm_base_url: str = "http://llm:11434"
    llm_model: str = "llama3.1:8b-instruct"
    llm_fast_model: str = "llama3.1:8b-instruct"
    llm_default_model: str = "llama3.1:8b-instruct"
    llm_strong_model: str = "llama3.1:8b-instruct"
    vision_model: str = "llama3.2-vision:11b"
    vision_model_fallbacks: str = "llava:7b,llava:13b,moondream:latest"
    llm_timeout_seconds: int = 60
    llm_cache_enabled: bool = True
    llm_cache_version: str = "docgen-v5"
    llm_cache_max_entries: int = 1000
    llm_capability_ttl_seconds: int = 300

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "doc_optimizer"

    enable_policy_guards: bool = True
    max_input_chars: int = 80000
    artifact_storage_dir: str = "/tmp/doc_optimizer_artifacts"
    enforce_identity_headers: bool = True
    allowed_roles: str = "author,reviewer,admin"
    rag_chunk_size_chars: int = 900
    rag_chunk_overlap_chars: int = 180
    rag_top_k_chunks: int = 8
    rag_use_embeddings: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
