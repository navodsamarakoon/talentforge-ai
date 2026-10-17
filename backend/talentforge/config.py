from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://talentforge:talentforge@localhost:5432/talentforge"
    jwt_secret: SecretStr = SecretStr("")
    jwt_expiry_minutes: int = Field(default=60, ge=5, le=1440)
    invitation_expiry_hours: int = Field(default=72, ge=1, le=720)
    sandbox_image: str = "python:3.12-alpine"
    sandbox_runner_url: str = "http://sandbox-runner:8001"
    sandbox_timeout_seconds: int = Field(default=5, ge=1, le=30)
    sandbox_max_code_chars: int = Field(default=20_000, ge=100, le=100_000)
    ai_enabled: bool = False
    ai_timeout_seconds: int = Field(default=270, ge=5, le=300)
    retrieval_enabled: bool = False
    cors_origins: str = "http://localhost:5173"

    @property
    def jwt_secret_value(self) -> str:
        value = self.jwt_secret.get_secret_value()
        if len(value) < 32:
            raise ValueError("JWT_SECRET must contain at least 32 characters.")
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
