"""
Role permission map and enforcement dependency.

Requirement 13.1: role-based access control with five predefined roles.
Requirement 13.2: enforce permissions within 2 seconds; return 403 on denial.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.dependencies.auth import TokenPayload, get_current_user

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Permission map: role -> set of allowed operations
# ---------------------------------------------------------------------------

ROLE_PERMISSIONS: dict[str, set[str]] = {
    "super_admin": {
        "tenant:create", "tenant:approve", "tenant:suspend", "tenant:deactivate",
        "tenant:update", "tenant:read", "tenant:rotate_key",
        "schema:create", "schema:read", "schema:update", "schema:delete", "schema:export",
        "document:upload", "document:read", "document:download", "document:list",
        "document:revoke", "document:bulk_upload", "document:bulk_revoke",
        "verification:create", "verification:read",
        "audit:read", "audit:export",
        "webhook:create", "webhook:read", "webhook:update", "webhook:delete",
        "notification:read", "notification:update",
        "user:create", "user:read", "user:update", "user:delete",
        "search:query",
    },
    "tenant_admin": {
        "tenant:read", "tenant:update", "tenant:rotate_key",
        "schema:create", "schema:read", "schema:update", "schema:delete", "schema:export",
        "document:upload", "document:read", "document:download", "document:list",
        "document:revoke", "document:bulk_upload", "document:bulk_revoke",
        "verification:read",
        "audit:read", "audit:export",
        "webhook:create", "webhook:read", "webhook:update", "webhook:delete",
        "notification:read",
        "user:create", "user:read", "user:update", "user:delete",
        "search:query",
    },
    "issuer": {
        "schema:read",
        "document:upload", "document:read", "document:download", "document:list",
        "document:revoke", "document:bulk_upload", "document:bulk_revoke",
        "search:query",
    },
    "beneficiary": {
        "document:read", "document:download", "document:list",
        "verification:create",
        "notification:read", "notification:update",
    },
    "verifier": {
        "verification:read",
    },
}


def require_permission(operation: str):
    """Return a FastAPI dependency that enforces the given permission.

    Usage:
        @router.post("/schemas", dependencies=[Depends(require_permission("schema:create"))])
        async def create_schema(...): ...
    """

    async def _check(
        user: Annotated[TokenPayload, Depends(get_current_user)],
    ) -> TokenPayload:
        for role in user.roles:
            allowed = ROLE_PERMISSIONS.get(role, set())
            if operation in allowed:
                return user

        logger.warning(
            "RBAC denied: user=%s roles=%s attempted=%s",
            user.sub,
            user.roles,
            operation,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "FORBIDDEN",
                "message": f"Insufficient permissions for operation: {operation}",
            },
        )

    return _check
