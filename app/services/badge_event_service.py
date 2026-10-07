"""Append-only badge analytics event service (FR-7).

Records ``BadgeEvent`` rows that U3 later aggregates into daily analytics.
Mirrors :class:`app.services.audit_service.AuditService`: events are added to
the caller's transaction and committed by the caller, so an event is never
persisted for an operation that ultimately rolled back.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.badge import BadgeEvent

logger = logging.getLogger(__name__)

# Mirror of the CHECK constraint in migration 005.
_EVENT_TYPES: frozenset[str] = frozenset(
    {"issued", "accepted", "published", "shared", "verified", "viewed", "revoked"}
)


class BadgeEventService:
    """Records append-only badge analytics events."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    def record(
        self,
        tenant_id: UUID,
        event_type: str,
        badge_class_id: UUID | None = None,
        assertion_id: UUID | None = None,
        channel: str | None = None,
    ) -> None:
        """Add a badge event to the current transaction.

        Does not commit — the caller's transaction owns the lifecycle so the
        event and the state change it describes succeed or fail together.
        """
        if event_type not in _EVENT_TYPES:
            raise ValueError(f"unknown badge event_type: {event_type!r}")
        self.db.add(
            BadgeEvent(
                tenant_id=tenant_id,
                event_type=event_type,
                badge_class_id=badge_class_id,
                assertion_id=assertion_id,
                channel=channel,
            )
        )


async def get_badge_event_service(db: AsyncSession = Depends(get_db)) -> BadgeEventService:
    return BadgeEventService(db=db)
