"""
Authentication dependencies for FastAPI route handlers.

Provides:
  - decode_access_token: non-raising JWT decode, returns None on failure.
  - bearer_token_from_request: pulls the raw bearer token off a Request.
  - get_current_user: validates the JWT Bearer token and returns user claims.
  - get_current_tenant_id: extracts tenant_id from the validated token.

``decode_access_token`` is deliberately non-raising so middleware can resolve
the tenant *before* endpoint dependencies run.  Middleware executes ahead of
dependency resolution, so anything that relies on ``request.state.tenant_id``
being set by ``get_current_user`` would never fire.  Rejecting bad tokens
remains the job of ``get_current_user``.
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

_bearer_scheme = HTTPBearer(auto_error=True)

_BEARER_PREFIX = "bearer "


@dataclass(frozen=True, slots=True)
class TokenPayload:
    """Decoded JWT payload with typed fields."""

    sub: str
    tenant_id: UUID
    roles: list[str]
    exp: int


def decode_access_token(token: str) -> TokenPayload | None:
    """Decode and validate *token*, returning ``None`` if it is unusable.

    Never raises.  Callers that must reject the request (``get_current_user``)
    translate ``None`` into a 401; callers that merely want the tenant context
    (middleware) can skip their work instead.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        return None

    try:
        return TokenPayload(
            sub=payload["sub"],
            tenant_id=UUID(payload["tenant_id"]),
            roles=payload.get("roles", []),
            exp=payload["exp"],
        )
    except (KeyError, ValueError) as exc:
        logger.warning("JWT payload malformed: %s", exc)
        return None


def bearer_token_from_request(request: Request) -> str | None:
    """Extract the raw bearer token from the Authorization header, if present."""
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith(_BEARER_PREFIX):
        return None
    token = header[len(_BEARER_PREFIX):].strip()
    return token or None


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> TokenPayload:
    """Decode and validate the JWT Bearer token.

    Also (re)stores tenant_id on ``request.state`` so service-layer helpers can
    read it.  TenantContextMiddleware sets the same value earlier in the
    request lifecycle; this keeps the two consistent.
    """
    token_data = decode_access_token(credentials.credentials)
    if token_data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_TOKEN", "message": "Token is invalid or expired."},
            headers={"WWW-Authenticate": "Bearer"},
        )

    request.state.tenant_id = str(token_data.tenant_id)
    return token_data


async def get_current_tenant_id(
    user: Annotated[TokenPayload, Depends(get_current_user)],
) -> UUID:
    """Return the authenticated tenant_id (convenience dependency)."""
    return user.tenant_id
