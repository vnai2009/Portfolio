"""Authentication.

The client presents a bearer token. We store only its SHA-256 hash — the
token itself is shown exactly once, at issue time.

This is deliberately a *bearer API token*, not a password: the token is 256
bits of random data, so a fast hash is appropriate. Passwords need a slow
KDF precisely because they are low-entropy.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserModel

#: ``auto_error=False`` so a missing header produces our 401, not FastAPI's.
bearer_scheme = HTTPBearer(auto_error=False)

TOKEN_PREFIX = "wpx_"


def generate_token() -> str:
    """Mint a new API token. 32 bytes of entropy, URL-safe."""
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Hash a bearer token for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    """Resolve the bearer token to its owner, or raise 401."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Missing bearer token.")

    if credentials.scheme.lower() != "bearer":
        raise _unauthorized("Authorization scheme must be 'Bearer'.")

    token_hash = hash_token(credentials.credentials)
    user = db.query(UserModel).filter(UserModel.token_hash == token_hash).first()

    if user is None:
        raise _unauthorized("Invalid token.")

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is disabled."
        )

    return user


def require_user(user: UserModel = Depends(get_current_user)) -> UserModel:
    """An active owner. Use as the dependency on every owner-scoped route."""
    return user
