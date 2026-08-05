"""
Authentication dependencies for FastAPI route handlers.

Provides:
  - get_current_user: validates JWT Bearer token and returns user claims.
  - get_current_tenant_id: extracts tenant_id from the validated token.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_bearer_scheme = HTTPBearer(auto_error=True)


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded JWT payload with typed fields."""

    sub: str
    tenant_id: UUID
    roles: list[str]
    exp: int


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> TokenPayload:
    """Decode and validate the JWT Bearer token.

    On success, also stores tenant_id on ``request.state`` for downstream
    middleware (TenantContextMiddleware) and dependencies.
    """
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token is invalid or expired."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        token_data = TokenPayload(
            sub=payload["sub"],
            tenant_id=UUID(payload["tenant_id"]),
            roles=payload.get("roles", []),
            exp=payload["exp"],
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token payload is malformed."},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    # Store tenant_id for TenantContextMiddleware
    request.state.tenant_id = str(token_data.tenant_id)
    return token_data


async def get_current_tenant_id(
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> UUID:
    """Return the authenticated tenant_id (convenience dependency)."""
    return user.tenant_id
