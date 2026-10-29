"""HTTP endpoints for the portfolio.

Every route is scoped to the authenticated owner. One owner can never read,
write or delete another owner's rows.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import require_user
from app.database import get_db
from app.models import PropertyModel, UserModel
from app.schemas import (
    EntityTransferRequest,
    PropertyCreateRequest,
    PropertyResponse,
)
from app.services.property_service import ProviderUnavailableError, PropertyService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/portfolio", tags=["Portfolio Management"])


def get_property_service() -> PropertyService:
    """Construct the service, wiring in Domain credentials when present.

    A FastAPI dependency, so tests can override it without touching the
    routes themselves.
    """
    from app.config import settings
    from app.services.domain_client import DomainClient

    api_key = settings.domain_api_key_value
    client = None
    if api_key:
        client = DomainClient(
            api_key=api_key,
            base_url=settings.domain_base_url,
            timeout=settings.domain_timeout,
            connect_timeout=settings.domain_connect_timeout,
            retries=settings.domain_retries,
            backoff_factor=settings.domain_backoff_factor,
            auth_mode=settings.domain_auth_mode,
        )
    return PropertyService(
        client=client,
        allow_estimate_fallback=settings.allow_estimate_fallback,
    )


@router.get("/properties", response_model=list[PropertyResponse])
def list_properties(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_user),
):
    """Every property this owner holds, newest first."""
    query = (
        db.query(PropertyModel)
        .filter(PropertyModel.owner_id == user.id)
        .order_by(PropertyModel.created_at.desc(), PropertyModel.id.desc())
    )
    return query.limit(limit).offset(offset).all()


@router.post("/properties", response_model=PropertyResponse, status_code=status.HTTP_201_CREATED)
def add_property(
    payload: PropertyCreateRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_user),
    service: PropertyService = Depends(get_property_service),
):
    """Value an address and add it to the owner's portfolio."""
    try:
        valuation = service.get_valuation(payload.query, payload.purchase_price)
    except ProviderUnavailableError as exc:
        logger.error("Valuation provider unavailable and fallback is disabled: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Valuation provider unavailable: {exc}",
        ) from exc

    new_property = PropertyModel(
        owner_id=user.id,
        name=valuation.name,
        entity_type=payload.entity_type.value,
        purchase_price=payload.purchase_price,
        current_value=valuation.current_value,
        last_sold_date=valuation.last_sold_date,
        current_rent=valuation.current_rent,
        provenance_source=valuation.provenance_source,
        source_url=valuation.source_url,
        domain_property_id=valuation.domain_property_id,
    )

    db.add(new_property)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You already hold a property at {valuation.name}.",
        ) from exc
    db.refresh(new_property)

    return new_property


@router.get("/properties/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_user),
):
    """One property, if this owner holds it."""
    prop = (
        db.query(PropertyModel)
        .filter(PropertyModel.id == property_id, PropertyModel.owner_id == user.id)
        .first()
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")
    return prop


@router.post("/properties/{property_id}/transfer", response_model=PropertyResponse)
def transfer_property(
    property_id: int,
    payload: EntityTransferRequest,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_user),
):
    """Move a property between entity types (personal / super / company)."""
    prop = (
        db.query(PropertyModel)
        .filter(PropertyModel.id == property_id, PropertyModel.owner_id == user.id)
        .first()
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    prop.entity_type = payload.target_entity.value
    db.commit()
    db.refresh(prop)
    return prop


@router.delete("/properties/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(
    property_id: int,
    db: Session = Depends(get_db),
    user: UserModel = Depends(require_user),
):
    """Remove a property from the owner's portfolio."""
    prop = (
        db.query(PropertyModel)
        .filter(PropertyModel.id == property_id, PropertyModel.owner_id == user.id)
        .first()
    )
    if prop is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Property not found")

    db.delete(prop)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
