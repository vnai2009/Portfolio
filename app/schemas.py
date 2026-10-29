"""Pydantic v2 contracts.

One schema layer for requests *and* responses. Anything not declared here
cannot leak to a client.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class EntityType(str, Enum):
    """How the property is held."""

    personal = "personal"
    super = "super"
    company = "company"


class PropertyCreateRequest(BaseModel):
    """Body for ``POST /api/portfolio/properties``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    query: str = Field(
        ...,
        min_length=3,
        max_length=500,
        description="Property address or listing URL",
    )
    purchase_price: Decimal = Field(
        ...,
        gt=0,
        max_digits=14,
        decimal_places=2,
        description="Price paid, in AUD",
    )
    entity_type: EntityType = Field(
        ...,
        description="How the property is held",
    )

    @field_validator("query")
    @classmethod
    def _query_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class PropertyResponse(BaseModel):
    """A stored property.

    Built with ``from_attributes`` so FastAPI can serialise an ORM row
    directly. Columns absent from this model cannot leak.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    entity_type: EntityType
    purchase_price: Decimal
    current_value: Decimal
    last_sold_date: date | None = None
    current_rent: Decimal | None = None
    provenance_source: str | None = None
    source_url: HttpUrl | None = None


class EntityTransferRequest(BaseModel):
    """Body for ``POST /api/portfolio/properties/{id}/transfer``."""

    target_entity: EntityType


class TokenRequest(BaseModel):
    """Body for ``POST /auth/token`` — exchanges an email for an API token."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=120)


class TokenResponse(BaseModel):
    """An issued API token.

    Shown exactly once — only the hash is stored.
    """

    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    display_name: str
