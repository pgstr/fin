from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    environment: str = Field("development", alias="ENVIRONMENT")
    database_path: Path = Field(Path("var/finanzplaner.db"), alias="DATABASE_PATH")
    backup_dir: Path = Field(Path("var/backups"), alias="BACKUP_DIR")
    session_secret: str = Field("development-session-secret-change-me", alias="SESSION_SECRET")
    setup_token: str = Field("development-setup-token", alias="SETUP_TOKEN")
    cookie_secure: bool = Field(False, alias="COOKIE_SECURE")
    trusted_hosts: str = Field("localhost,127.0.0.1,testserver", alias="TRUSTED_HOSTS")
    max_upload_bytes: int = Field(10 * 1024 * 1024, alias="MAX_UPLOAD_BYTES")
    session_hours: int = Field(24 * 14, alias="SESSION_HOURS")
    login_attempts: int = Field(5, alias="LOGIN_ATTEMPTS")
    login_window_seconds: int = Field(15 * 60, alias="LOGIN_WINDOW_SECONDS")
    timezone: str = Field("Europe/Berlin", alias="TZ")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @field_validator("database_path", "backup_dir", mode="before")
    @classmethod
    def expand_path(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @model_validator(mode="after")
    def validate_production_secrets(self) -> Settings:
        if self.environment == "production":
            if len(self.session_secret) < 32 or self.session_secret.startswith("development-"):
                raise ValueError("SESSION_SECRET must contain at least 32 non-default characters")
            if len(self.setup_token) < 16 or self.setup_token.startswith("development-"):
                raise ValueError("SETUP_TOKEN must contain at least 16 non-default characters")
        return self

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.resolve()}"

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def mcp_allowed_hosts(self) -> list[str]:
        return [value for host in self.trusted_host_list for value in (host, f"{host}:*")]

    @property
    def mcp_allowed_origins(self) -> list[str]:
        return [
            value
            for host in self.trusted_host_list
            for scheme in ("http", "https")
            for value in (f"{scheme}://{host}", f"{scheme}://{host}:*")
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
