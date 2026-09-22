from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    cache_max_entries: int = Field(default=1024, ge=1, le=100_000)
    cache_ttl_seconds: float = Field(default=5.0, gt=0, le=60)
