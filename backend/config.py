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

    # Clé admin : routes d'administration (meetings, classify, referential) + stats globales.
    dashboard_api_key: str | None = None
    jwt_secret: str | None = None

    backend_host: str = "0.0.0.0"
    backend_port: int = 8000

    # Worker de synchronisation périodique
    sync_interval_minutes: int = 15
    sync_lookback_days: int = 7
    sync_lookahead_days: int = 30

    def google_configured(self) -> bool:
        return bool(
            self.google_client_id
            and self.google_client_secret
            and self.token_encryption_key
            and len(self.token_encryption_key) >= 16
        )

    def startup_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.jwt_secret or len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET manquant ou trop court (32 caractères minimum)")
        if not self.dashboard_api_key or len(self.dashboard_api_key) < 12:
            problems.append("DASHBOARD_API_KEY manquante ou trop courte (12 caractères minimum)")
        return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()
