from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Radeski CRM"
    environment: str = "local"  # local | test | production
    tz: str = "Asia/Tashkent"

    database_url: str = "postgresql+asyncpg://crm:crm@db:5432/crm"
    redis_url: str = "redis://redis:6379/0"

    # Auth
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 15
    session_idle_minutes: int = 30  # TZ 5: session closes after 30 min of inactivity
    session_absolute_hours: int = 12  # one working shift
    login_max_attempts: int = 5
    login_lock_minutes: int = 15

    # External services (filled in later phases)
    openai_api_key: str = ""
    site_api_url: str = "https://api.radeski.uz"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    weak = len(settings.jwt_secret) < 32 or settings.jwt_secret == "dev-only-change-me"
    if settings.is_production and weak:
        raise RuntimeError("JWT_SECRET must be set in production (at least 32 characters)")
    return settings
