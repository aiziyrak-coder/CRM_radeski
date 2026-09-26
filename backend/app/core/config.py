from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Radeski CRM"
    environment: str = "local"  # local | production
    tz: str = "Asia/Tashkent"

    database_url: str = "postgresql+asyncpg://crm:crm@db:5432/crm"
    redis_url: str = "redis://redis:6379/0"

    # External services (filled in later phases)
    openai_api_key: str = ""
    site_api_url: str = "https://api.radeski.uz"


@lru_cache
def get_settings() -> Settings:
    return Settings()
