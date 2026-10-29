"""SQLAlchemy ORM models.

Money is ``Numeric`` — never ``Float``. Totals compound errors, and a
portfolio is totalled.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class UserModel(Base):
    """An API consumer. Every property row is scoped to exactly one owner."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # PBKDF2-HMAC-SHA256, hex encoded. Never store the token itself.
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    properties: Mapped[list["PropertyModel"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )


class PropertyModel(Base):
    """A residential property held personally, in super, or via a company."""

    __tablename__ = "properties"

    __table_args__ = (
        UniqueConstraint("owner_id", "name", name="uq_properties_owner_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    owner_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)

    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    current_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    last_sold_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_rent: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    # What actually produced the number. See the design principles in README.
    provenance_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Domain's own identifier for the property, when resolved.
    domain_property_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped[UserModel] = relationship(back_populates="properties")
