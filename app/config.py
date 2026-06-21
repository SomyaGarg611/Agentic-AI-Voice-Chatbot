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


settings = Settings()
