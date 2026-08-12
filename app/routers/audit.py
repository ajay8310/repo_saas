"""
Audit log endpoints — read and export.

Requirements: 10.1, 10.5
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.dependencies.auth import TokenPayload, get_current_user
from app.middleware.tenant_context import set_tenant_context
from app.models.audit import AuditLog
from app.rbac.permissions import require_permission

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


class AuditLogResponse(BaseModel):
    id: str
    actor_id: str
    actor_role: str
    operation: str
    resource_type: str
    resource_id: str
    outcome: str
    metadata: dict
    created_at: str


class AuditListResponse(BaseModel):
    items: list[AuditLogResponse]
    total: int
    page: int
    page_size: int


@router.get(
    "",
    response_model=AuditListResponse,
    dependencies=[Depends(require_permission("audit:read"))],
)
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    operation: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AuditListResponse:
    """List audit logs for the tenant. Single-table query."""
    await set_tenant_context(db, str(user.tenant_id))
    offset = (page - 1) * page_size

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    count_stmt = select(func.count(AuditLog.id))

    if operation:
        stmt = stmt.where(AuditLog.operation == operation)
        count_stmt = count_stmt.where(AuditLog.operation == operation)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
        count_stmt = count_stmt.where(AuditLog.resource_type == resource_type)

    stmt = stmt.limit(page_size).offset(offset)

    result = await db.execute(stmt)
    logs = result.scalars().all()
    total = (await db.execute(count_stmt)).scalar() or 0

    items = [
        AuditLogResponse(
            id=str(log.id),
            actor_id=log.actor_id,
            actor_role=log.actor_role,
            operation=log.operation,
            resource_type=log.resource_type,
            resource_id=log.resource_id,
            outcome=log.outcome,
            metadata=log.metadata_,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]

    return AuditListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/export",
    dependencies=[Depends(require_permission("audit:export"))],
)
async def export_audit_logs(
    format: Literal["json", "csv"] = Query(default="json"),
    user: TokenPayload = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export audit logs as JSON or CSV (Req 10.5)."""
    import csv
    import io
    import json

    await set_tenant_context(db, str(user.tenant_id))

    result = await db.execute(
        select(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(100_000)
    )
    logs = result.scalars().all()

    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["id", "actor_id", "actor_role", "operation", "resource_type", "resource_id", "outcome", "created_at"])
        for log in logs:
            writer.writerow([str(log.id), log.actor_id, log.actor_role, log.operation, log.resource_type, log.resource_id, log.outcome, log.created_at.isoformat()])
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=audit-logs.csv"},
        )
    else:
        data = [
            {"id": str(log.id), "actor_id": log.actor_id, "operation": log.operation,
             "resource_type": log.resource_type, "resource_id": log.resource_id,
             "outcome": log.outcome, "created_at": log.created_at.isoformat()}
            for log in logs
        ]
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit-logs.json"},
        )
