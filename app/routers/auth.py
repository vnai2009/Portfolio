"""Token issuing.

``POST /auth/token`` returns a bearer token for an email address, creating
the owner record on first use. It is a local-development convenience — a
production deployment would verify the email before minting a token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.dependencies import generate_token, hash_token, require_user
from app.database import get_db
from app.models import UserModel
from app.schemas import TokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/token", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def issue_token(payload: TokenRequest, db: Session = Depends(get_db)):
    """Issue (or re-issue) an API token for an email address."""
    email = payload.email.strip().lower()
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
