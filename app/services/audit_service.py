"""
Append-only audit log service.

Writes audit entries within the same transaction as the originating operation.
No joins — direct INSERT into audit_logs table.

Requirements: 10.1, 10.2, 10.7
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """Records immutable audit log entries."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        tenant_id: UUID,
        actor_id: str,
        actor_role: str,
        operation: str,
        resource_type: str,
        resource_id: str,
        outcome: str = "success",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Write an audit log entry.

        This must be called within the same transaction as the originating
        operation. If the INSERT fails, the transaction rolls back (Req 10.7).
        """
        entry = AuditLog(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation=operation,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            metadata_=metadata or {},
        )
        self.db.add(entry)
        # Don't commit here — let the caller's transaction handle it


async def get_audit_service(db: AsyncSession = Depends(get_db)) -> AuditService:
    return AuditService(db=db)
