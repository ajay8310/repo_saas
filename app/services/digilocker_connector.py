"""
DigiLocker async push connector with retry logic.

No joins — queries digilocker_pushes by document_id.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.digilocker import DigiLockerPush

logger = logging.getLogger(__name__)


class DigiLockerConnector:
    """Pushes documents to DigiLocker with retry. No joins."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    async def enqueue_push(
        self, tenant_id: UUID, document_id: UUID
    ) -> DigiLockerPush:
        """Create a push record for async processing."""
        await set_tenant_context(self.db, str(tenant_id))
        push = DigiLockerPush(
            tenant_id=tenant_id,
            document_id=document_id,
            status="pending",
        )
        self.db.add(push)
        await self.db.commit()
        await self.db.refresh(push)
        return push

    async def attempt_push(
        self, push_id: UUID, tenant_id: UUID | None = None
    ) -> bool:
        """Attempt to push a document to DigiLocker.

        On failure: increments attempt_count, schedules retry.
        After max retries: marks permanently_failed.

        *tenant_id* is optional only for backwards compatibility. Supply it
        wherever it is known: ``digilocker_pushes`` is RLS-protected, so without
        a tenant context the SELECT below matches no rows.
        """
        if tenant_id is not None:
            await set_tenant_context(self.db, str(tenant_id))

        result = await self.db.execute(
            select(DigiLockerPush).where(DigiLockerPush.id == push_id)
        )
        push = result.scalar_one_or_none()
        if push is None:
            return False

        push.attempt_count += 1
        push.last_attempt_at = datetime.now(timezone.utc)

        try:
            # In production: OAuth2 auth + actual DigiLocker API call
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Placeholder — real impl would call DigiLocker issuer API
                response = await client.post(
                    "https://api.digilocker.gov.in/placeholder",
                    json={"document_id": str(push.document_id)},
                )
                if 200 <= response.status_code < 300:
                    # 'success' — not 'delivered'.  The digilocker_pushes
                    # status CHECK constraint permits
                    # pending|success|failed|permanently_failed|retrying, so
                    # writing 'delivered' raised a CheckViolation on every
                    # successful push.
                    push.status = "success"
                    await self.db.commit()
                    return True
        except Exception as exc:
            logger.warning(
                "DigiLocker push failed (attempt %d): %s",
                push.attempt_count, exc,
            )
            push.failure_reason = str(exc)

        # Check if max retries exhausted
        if push.attempt_count >= self.settings.digilocker_max_retries:
            push.status = "permanently_failed"
            logger.error(
                "DigiLocker push permanently failed: push_id=%s doc=%s",
                push_id, push.document_id,
            )
        else:
            push.status = "retrying"

        await self.db.commit()
        return False


async def get_digilocker_connector(
    db: AsyncSession = Depends(get_db),
) -> DigiLockerConnector:
    return DigiLockerConnector(db=db, settings=get_settings())
