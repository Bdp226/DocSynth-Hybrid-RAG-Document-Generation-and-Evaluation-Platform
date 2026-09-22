from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_NAME = "docsynth-orchestrator"
SERVICE_VERSION = "1.0.0"


class Settings(BaseSettings):
    app_env: str = "dev"
    log_level: str = "INFO"
    # The service is always deployed behind an ingress/service boundary, and a
    # container must bind the container interface to be reachable at all.
    # Not a directly exposed listener.
    host: str = "0.0.0.0"  # nosec B104
    port: int = 8080

    # Build provenance. Populated by the container build (`--build-arg`) so that
    # /version can tie a running replica back to an exact commit.
    git_commit: str = "unknown"
    build_time: str = "unknown"

    llm_base_url: str = "http://llm:11434"
    llm_model: str = "llama3.1:8b-instruct"
    llm_fast_model: str = "llama3.1:8b-instruct"
    llm_default_model: str = "llama3.1:8b-instruct"
    llm_strong_model: str = "llama3.1:8b-instruct"
    vision_model: str = "llama3.2-vision:11b"
    vision_model_fallbacks: str = "llava:7b,llava:13b,moondream:latest"
    llm_timeout_seconds: int = 60
    llm_cache_enabled: bool = True
    llm_cache_max_entries: int = 1000
    llm_capability_ttl_seconds: int = 300

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "doc_optimizer"

    enable_policy_guards: bool = True
    max_input_chars: int = 80000
    # Local-development fallback only. Every deployed path overrides this:
    # the Dockerfile and both compose/k8s manifests set ARTIFACT_STORAGE_DIR to
    # /var/lib/docsynth/artifacts on a dedicated, non-world-writable volume.
    artifact_storage_dir: str = "/tmp/doc_optimizer_artifacts"  # nosec B108
    enforce_identity_headers: bool = True
    allowed_roles: str = "author,reviewer,admin"
    rag_chunk_size_chars: int = 900
    rag_chunk_overlap_chars: int = 180
    rag_top_k_chunks: int = 8
    rag_use_embeddings: bool = True

    # Cost tracking: per-token pricing in USD for each model (used for observability).
    # For self-hosted local models, set to 0. For API-based models, set realistic rates.
    llm_cost_per_1k_input_tokens: float = 0.0
    llm_cost_per_1k_output_tokens: float = 0.0
    vision_model_cost_per_1k_input_tokens: float = 0.0
    vision_model_cost_per_1k_output_tokens: float = 0.0

    # --- Ingress protection -------------------------------------------------
    # A single compose call can occupy a worker for tens of seconds, so the
    # service protects itself with a per-identity sliding window rather than a
    # global counter. Set to 0 to disable (useful for load testing).
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10
    rate_limit_exempt_paths: str = "/healthz,/readyz,/health,/version,/metrics"
    max_request_bytes: int = 25_000_000

    # --- Cross-origin access ------------------------------------------------
    # Disabled by default: the UI is served same-origin. Enable explicitly with
    # an allow-list when embedding the API in another front end.
    cors_enabled: bool = False
    cors_allow_origins: str = ""

    # --- Readiness ----------------------------------------------------------
    # When true, /readyz fails if the configured text model is unreachable.
    # Kept opt-in so local development without a running LLM still reports ready.
    readiness_requires_llm: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def rate_limit_exempt_path_set(self) -> set[str]:
        return {path.strip() for path in self.rate_limit_exempt_paths.split(",") if path.strip()}

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allow_origins.split(",") if origin.strip()]


settings = Settings()
