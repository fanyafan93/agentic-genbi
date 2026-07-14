from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """Runtime settings required by the currently implemented application shell."""

    model_config = SettingsConfigDict(env_file=PROJECT_ENV_FILE, extra="ignore")

    app_env: Literal["development", "test", "production"]
    database_url: SecretStr
    allowed_tables: Annotated[tuple[str, ...], NoDecode] = ("sales_channel_monthly",)
    minimax_api_key: SecretStr | None = None
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_model: str = "MiniMax-M3"
    max_query_rows: int = Field(default=500, ge=1, le=10_000)
    query_timeout_ms: int = Field(default=5_000, ge=100, le=60_000)
    max_sql_retries: int = Field(default=2, ge=0, le=2)

    @field_validator("allowed_tables", mode="before")
    @classmethod
    def parse_allowed_tables(cls, value: str | tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(value, str):
            return tuple(name.strip() for name in value.split(",") if name.strip())
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
