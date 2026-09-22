from typing import Optional

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    cache_max_entries: int = Field(default=1024, ge=1, le=100_000)
    cache_ttl_seconds: float = Field(default=5.0, gt=0, le=60)
    api_key: Optional[SecretStr] = Field(default=None, min_length=32)
    require_api_key: bool = False

    @model_validator(mode="after")
    def validate_auth(self):
        if self.require_api_key and self.api_key is None:
            raise ValueError("API_KEY is required when REQUIRE_API_KEY=true")
        return self
