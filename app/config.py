from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # LLM
    anthropic_api_key: str
    claude_model: str = "claude-sonnet-4-6"

    # STT
    deepgram_api_key: Optional[str] = None

    # TTS
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: str = "Xb7hH8MSUJpSbSDYk0k2"  # Alice — premade, free tier
    elevenlabs_model: str = "eleven_turbo_v2_5"

    # Search
    tavily_api_key: Optional[str] = None

    # Observability
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"

    # ── Auth ──────────────────────────────────────────────────────────────
    # Google Sign-In: set GOOGLE_CLIENT_ID (OAuth 2.0 Web client) to enable the
    # real "Sign in with Google" button. When empty, a dev email-login is used
    # so the multi-user flow still works locally without Google setup.
    google_client_id: Optional[str] = None
    # Secret used to sign our own session JWTs. Set a strong value in prod.
    jwt_secret: str = "dev-insecure-change-me"
    jwt_ttl_hours: int = 168  # 7 days

    # Rate limits
    max_turns_per_min: int = 20      # per WebSocket connection
    max_uploads_per_min: int = 10    # per client IP

    @property
    def has_deepgram(self) -> bool:
        return bool(self.deepgram_api_key)

    @property
    def has_elevenlabs(self) -> bool:
        return bool(self.elevenlabs_api_key)

    @property
    def has_tavily(self) -> bool:
        return bool(self.tavily_api_key)

    @property
    def has_langfuse(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def has_google(self) -> bool:
        return bool(self.google_client_id)


settings = Settings()
