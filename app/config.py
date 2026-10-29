"""Application settings.

Every value is read from the environment (or ``.env``) and validated **once**,
at import time. A bad value fails at startup, not at 3 AM.

Resolution order (highest priority first):

1. Environment variable
2. ``.env`` file
3. The default declared here
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed configuration for the Wealthy Property Portfolio Engine."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="WEALTHY_",
        extra="ignore",
    )

    # --- Identity -------------------------------------------------------
    app_name: str = "Wealthy Property Portfolio Engine"
    app_version: str = "7.1.0"
    debug: bool = False

    # --- Persistence ----------------------------------------------------
    database_url: str = Field(
        ...,
        description="postgresql+psycopg://user:pass@host:5432/db",
    )
    auto_create_tables: bool = Field(
        default=False,
        description="Dev convenience only. Alembic owns the schema in production.",
    )

    # --- Domain.com.au AVM provider -------------------------------------
    domain_api_key: SecretStr | None = Field(
        default=None,
        description="Domain API key (x-api-key header, 'key_...' format).",
    )
    domain_auth_mode: str = Field(
        default="api_key",
        description="'api_key' sends x-api-key; 'bearer' sends Authorization: Bearer.",
    )
    domain_base_url: str = "https://api.domain.com.au"
    domain_timeout: float = 10.0
    domain_connect_timeout: float = 3.05
    domain_retries: int = 2
    domain_backoff_factor: float = 0.5

    # --- Provider failure behaviour -------------------------------------
    allow_estimate_fallback: bool = Field(
        default=True,
        description="Degrade to an algorithmic estimate when the provider is down.",
    )
    strict_provider: bool = Field(
        default=False,
        description=(
            "Return 502 instead of degrading. When true, a missing API key is a "
            "startup error rather than a warning."
        ),
    )

    # --- Transport ------------------------------------------------------
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    @field_validator("domain_auth_mode")
    @classmethod
    def _valid_auth_mode(cls, value: str) -> str:
        mode = value.strip().lower()
        if mode not in {"api_key", "bearer"}:
            raise ValueError("domain_auth_mode must be 'api_key' or 'bearer'.")
        return mode

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: Any) -> Any:
        """Accept a JSON array or a comma-separated string."""
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return value
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard_with_credentials(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError(
                "cors_origins cannot contain '*' — this API sends credentials. "
                "List explicit origins instead."
            )
        return value

    @model_validator(mode="after")
    def _strict_provider_needs_a_key(self) -> "Settings":
        if self.strict_provider and not self.domain_api_key:
            raise ValueError(
                "WEALTHY_STRICT_PROVIDER=true requires WEALTHY_DOMAIN_API_KEY to be set. "
                "Refusing to start — the app would otherwise serve estimates it "
                "cannot attribute."
            )
        return self

    @property
    def has_domain_credentials(self) -> bool:
        """True when a usable Domain API key is configured."""
        if self.domain_api_key is None:
            return False
        return bool(self.domain_api_key.get_secret_value().strip())

    @property
    def domain_api_key_value(self) -> str | None:
        """The Domain API key in plain text, or None when unset."""
        if not self.has_domain_credentials:
            return None
        assert self.domain_api_key is not None
        return self.domain_api_key.get_secret_value().strip()


settings = Settings()
