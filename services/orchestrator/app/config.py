from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080

    llm_base_url: str = "http://llm:11434"
    llm_model: str = "llama3.1:8b-instruct"
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
    artifact_storage_dir: str = "/tmp/doc_optimizer_artifacts"
    enforce_identity_headers: bool = True
    allowed_roles: str = "author,reviewer,admin"
    rag_chunk_size_chars: int = 900
    rag_chunk_overlap_chars: int = 180
    rag_top_k_chunks: int = 8
    rag_use_embeddings: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
