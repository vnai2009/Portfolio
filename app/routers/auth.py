"""Token issuing.

``POST /auth/token`` returns a bearer token for an email address.

Two modes, controlled by configuration:

* **Development** — ``WEALTHY_ALLOW_SELF_SERVICE_TOKENS=true`` (the default).
  Any email mints a token with no password. Convenient, and completely open.
* **Production** — ``WEALTHY_BOOTSTRAP_ADMIN_EMAIL`` and
  ``WEALTHY_BOOTSTRAP_ADMIN_SECRET`` are set. Only that one email may mint a
  token, and only by presenting the shared secret. Every other email is
  refused with 403.

The secret is compared in constant time, and it never reaches the log, the
response body, or the database.
"""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import generate_token, hash_token, require_user
from app.config import settings
from app.database import get_db
from app.models import UserModel
from app.schemas import TokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _authorise(email: str, password: str | None) -> None:
    """Raise unless this caller may mint a token for ``email``.

    Closed mode — a bootstrap admin is configured. Only that one email may
    mint a token, and only by presenting the shared secret.

    Open mode — no bootstrap admin. Any email may mint a token with no
    password. That is permitted in development, and in production only when
    the operator has explicitly opted in.
    """
    if settings.has_bootstrap_admin:
        admin_email = (settings.bootstrap_admin_email or "").strip().lower()
        if email == admin_email:
            secret = settings.bootstrap_admin_secret_value or ""
            supplied = password or ""
            if not hmac.compare_digest(
                supplied.encode("utf-8"), secret.encode("utf-8")
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid credentials.",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Self-service token issuance is disabled. Only the bootstrap "
                "administrator may mint tokens."
            ),
        )

    if not (settings.allow_self_service_tokens or settings.debug):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token issuance is disabled on this deployment.",
        )


@router.post("/token", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def issue_token(payload: TokenRequest, db: Session = Depends(get_db)):
    """Issue (or re-issue) an API token for an email address."""
    email = payload.email.strip().lower()
    _authorise(email, payload.password)
    display_name = payload.display_name or email.split("@")[0]

    user = db.query(UserModel).filter(UserModel.email == email).first()
    if user is None:
        user = UserModel(email=email, display_name=display_name, token_hash="")
        db.add(user)
        db.flush()

    raw_token = generate_token()
    user.token_hash = hash_token(raw_token)
    user.display_name = display_name or user.display_name
    db.commit()
    db.refresh(user)

    return TokenResponse(
        access_token=raw_token,
        user_id=user.id,
        email=user.email,
        display_name=user.display_name,
    )


@router.get("/whoami")
def whoami(user: UserModel = Depends(require_user)):
    """Who the presented token belongs to."""
    return {
        "user_id": user.id,
        "email": user.email,
        "display_name": user.display_name,
    }
