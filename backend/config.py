from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://cultur_live:cultur_live@localhost:5432/cultur_live"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    token_encryption_key: str | None = None
    public_base_url: str = "http://localhost:8000"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    dashboard_api_key: str | None = None
    jwt_secret: str | None = None
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    def google_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.token_encryption_key
            and len(self.token_encryption_key) >= 16
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
