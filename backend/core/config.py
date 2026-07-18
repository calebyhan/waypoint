from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_service_key: str
    github_client_id: str
    github_client_secret: str
    token_encryption_key: str
    frontend_url: str = "http://localhost:3000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Gemini reliability knobs (timeouts are milliseconds, per google-genai HttpOptions).
    gemini_light_timeout_ms: int = 15_000  # questions / embeddings
    gemini_heavy_timeout_ms: int = 60_000  # skeleton / per-epic task generation
    gemini_retry_attempts: int = 3
    gemini_retry_wait_min: float = 2.0
    gemini_retry_wait_max: float = 20.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()  # type: ignore[call-arg]
