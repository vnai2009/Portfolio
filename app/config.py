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
    db_pool_size: int = Field(
        default=1,
        description="Persistent DB connections per worker. Keep small on Render.",
    )
    db_max_overflow: int = Field(
        default=2,
        description="Extra DB connections beyond pool_size, per worker.",
    )
    db_pool_timeout: int = Field(
        default=10,
        description="Seconds to wait for a pooled connection before failing.",
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

    # --- Authentication --------------------------------------------------
    bootstrap_admin_email: str | None = Field(
        default=None,
        description="The only email that may mint a token with the bootstrap secret.",
    )
    bootstrap_admin_secret: SecretStr | None = Field(
        default=None,
        description="Shared secret that unlocks a token for the admin email.",
    )
    allow_self_service_tokens: bool = Field(
        default=False,
        description=(
            "Permit token issuance for any email with no password. Dev "
            "convenience, off by default. Only consulted when no bootstrap "
            "admin is configured."
        ),
    )

    @field_validator("database_url")
    @classmethod
    def _force_psycopg3(cls, value: str) -> str:
        """Pin the driver to psycopg3.

        Render hands out a plain ``postgresql://`` URL, which SQLAlchemy
        routes to psycopg2. We ship psycopg3, so a URL copied straight from
        the Render dashboard would fail with a confusing
        ``ModuleNotFoundError: psycopg2``. Rewrite the scheme instead.
        """
        url = value.strip()
        rewrites = (
            ("postgresql+psycopg2://", "postgresql+psycopg://"),
            ("postgres+psycopg2://", "postgresql+psycopg://"),
            ("postgresql://", "postgresql+psycopg://"),
            ("postgres://", "postgresql+psycopg://"),
        )
        for prefix, replacement in rewrites:
            if url.startswith(prefix):
                return replacement + url[len(prefix) :]
        return url

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

    @model_validator(mode="after")
    def _bootstrap_admin_is_a_pair(self) -> "Settings":
        has_email = bool((self.bootstrap_admin_email or "").strip())
        has_secret = bool(
            self.bootstrap_admin_secret and self.bootstrap_admin_secret.get_secret_value().strip()
        )
        if has_email != has_secret:
            raise ValueError(
                "WEALTHY_BOOTSTRAP_ADMIN_EMAIL and WEALTHY_BOOTSTRAP_ADMIN_SECRET "
                "must be set together — one without the other cannot be used."
            )
        return self

    @model_validator(mode="after")
    def _production_closes_self_service_auth(self) -> "Settings":
        """Refuse to run a production build with an open token endpoint.

        ``POST /auth/token`` mints a working API token for any email, with no
        password. That is a convenience for local development and a critical
        hole in a publicly reachable deployment. The failure is loud and at
        startup, not a mystery later.

        A bootstrap admin closes it. If one is configured, closed mode is
        used regardless of ``allow_self_service_tokens``.
        """
        if self.debug:
            return self
        if self.has_bootstrap_admin:
            return self
        if self.allow_self_service_tokens:
            return self
        raise ValueError(
            "WEALTHY_DEBUG=false requires closed authentication. Set "
            "WEALTHY_BOOTSTRAP_ADMIN_EMAIL and WEALTHY_BOOTSTRAP_ADMIN_SECRET "
            "to enable the single-admin login, or set "
            "WEALTHY_ALLOW_SELF_SERVICE_TOKENS=true to accept an "
            "unauthenticated public token endpoint."
        )

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

    @property
    def has_bootstrap_admin(self) -> bool:
        """True when a bootstrap admin email and secret are both configured."""
        if not (self.bootstrap_admin_email or "").strip():
            return False
        if self.bootstrap_admin_secret is None:
            return False
        return bool(self.bootstrap_admin_secret.get_secret_value().strip())

    @property
    def bootstrap_admin_secret_value(self) -> str | None:
        """The bootstrap secret in plain text, or None when unset."""
        if not self.has_bootstrap_admin:
            return None
        assert self.bootstrap_admin_secret is not None
        return self.bootstrap_admin_secret.get_secret_value()


settings = Settings()
