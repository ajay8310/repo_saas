"""Badge issuance service (FR-4, FR-5, FR-6, S13).

Issues, revokes, and reads badge *assertions* — the instances awarded to
beneficiaries. Complements :class:`app.services.badge_service.BadgeService`
(which owns templates).

Key behaviours from approved decisions:

* **Single public identifier (Q1=B)**: the assertion ``id`` equals the linked
  ``documents.id`` / credential_id, so a badge is also a verifiable document and
  shares one hosted URL.
* **Expiry (Q2=C)**: an assertion is either fixed-period (``expires_at =
  issued_at + validity_days``) or non-expiring — never a mix. The value is taken
  from the badge class, so all instances of a class behave the same way.
* **Revocation (Q3=A)**: revoking sets ``status='revoked'`` + ``revoked_at`` +
  reason and forces ``public=false``. The hosted assertion still resolves (200)
  and reports ``revoked: true`` — it is not deleted or 404'd.
* **Bulk issue (FR-5)**: the router hands off to a Celery task; this service
  exposes the per-record issuing primitive the task calls.

Persistence follows the document-service conventions: RLS via
``set_tenant_context``, audit inside the transaction, best-effort async events.
"""

from __future__ import annotations

import logging
import secrets
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.services.audit_service import AuditService
from app.services.badge_event_service import BadgeEventService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IssueResult:
    """Result of issuing a single badge assertion."""

    assertion_id: str
    badge_class_id: str
    beneficiary_id: str
    issued_at: str
    expires_at: str | None
    status: str


class IssuanceService:
    """Issue, revoke, and read badge assertions."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._audit = AuditService(db)
        self._events = BadgeEventService(db)

    # ------------------------------------------------------------------
    # Issue (FR-4)
    # ------------------------------------------------------------------

    async def issue(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        beneficiary_id: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
        notify: bool = True,
    ) -> IssueResult:
        """Issue one badge assertion to a beneficiary (FR-4.1).

        Creates the assertion, derives expiry from the badge class, records an
        audit entry and an ``issued`` analytics event in the same transaction,
        then fires best-effort notification. The assertion id doubles as the
        credential/document id (Q1=B).
        """
        if not beneficiary_id or not beneficiary_id.strip():
            raise IssuanceValidationError("beneficiary_id must be non-empty")

        await set_tenant_context(self.db, str(tenant_id))

        badge_class = await self._get_class(badge_class_id)
        if badge_class is None:
            raise IssuanceValidationError("badge class not found")
        if badge_class.status != "active":
            raise IssuanceValidationError("cannot issue from an inactive badge class")

        assertion_id = uuid_mod.uuid4()
        issued_at = datetime.now(UTC)
        expires_at: datetime | None = None
        if badge_class.validity_days:
            expires_at = issued_at + timedelta(days=badge_class.validity_days)

        assertion = BadgeAssertion(
            id=assertion_id,
            issued_at=issued_at,
            tenant_id=tenant_id,
            badge_class_id=badge_class_id,
            beneficiary_id=beneficiary_id.strip(),
            # Single identifier: assertion id == credential/document id.
            document_id=assertion_id,
            expires_at=expires_at,
            status="active",
        )
        self.db.add(assertion)

        self._events.record(
            tenant_id=tenant_id,
            event_type="issued",
            badge_class_id=badge_class_id,
            assertion_id=assertion_id,
        )
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:issue",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
            metadata={"badge_class_id": str(badge_class_id), "beneficiary_id": beneficiary_id},
        )
        await self.db.commit()

        if notify:
            await self._notify_issued(tenant_id, beneficiary_id, assertion_id, badge_class.name)

        return IssueResult(
            assertion_id=str(assertion_id),
            badge_class_id=str(badge_class_id),
            beneficiary_id=beneficiary_id.strip(),
            issued_at=issued_at.isoformat(),
            expires_at=expires_at.isoformat() if expires_at else None,
            status="active",
        )

    # ------------------------------------------------------------------
    # Bulk issue (FR-5)
    # ------------------------------------------------------------------

    async def bulk_issue_enqueue(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        beneficiary_ids: list[str],
        actor_id: str = "system",
    ) -> str:
        """Validate a bulk request and enqueue it for background processing.

        Returns a job id. Per-record issuance is performed by the Celery task
        ``bulk_issue_badges`` calling :meth:`issue`, so a large batch never
        blocks the request thread (FR-5.1).
        """
        if not beneficiary_ids:
            raise IssuanceValidationError("beneficiary_ids must be non-empty")
        if len(beneficiary_ids) > self.settings.bulk_upload_max_records:
            raise IssuanceValidationError(
                f"bulk issue exceeds max of {self.settings.bulk_upload_max_records} records"
            )

        await set_tenant_context(self.db, str(tenant_id))
        badge_class = await self._get_class(badge_class_id)
        if badge_class is None or badge_class.status != "active":
            raise IssuanceValidationError("badge class not found or inactive")

        job_id = str(uuid_mod.uuid4())
        # Deferred import avoids a hard dependency on Celery at request time.
        from app.tasks.badge_bulk import bulk_issue_badges

        bulk_issue_badges.delay(
            job_id=job_id,
            tenant_id=str(tenant_id),
            badge_class_id=str(badge_class_id),
            beneficiary_ids=beneficiary_ids,
            actor_id=actor_id,
        )
        logger.info("Enqueued bulk badge issue job %s (%d recipients)", job_id, len(beneficiary_ids))
        return job_id

    # ------------------------------------------------------------------
    # Revoke (FR-6)
    # ------------------------------------------------------------------

    async def revoke(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        reason: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> BadgeAssertion:
        """Revoke an assertion the OB-compliant way (Q3=A).

        Sets status/revoked_at/reason and forces ``public=false`` so it leaves
        the directory, but the hosted assertion stays resolvable and reports
        ``revoked: true``.
        """
        if not reason or len(reason) > 500:
            raise IssuanceValidationError("revocation reason must be 1-500 characters")

        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise AssertionNotFoundError(assertion_id)
        if assertion.status == "revoked":
            raise AssertionAlreadyRevokedError(assertion_id)

        assertion.status = "revoked"
        assertion.revoked_at = datetime.now(UTC)
        assertion.revocation_reason = reason
        assertion.public = False

        self._events.record(
            tenant_id=tenant_id,
            event_type="revoked",
            badge_class_id=assertion.badge_class_id,
            assertion_id=assertion_id,
        )
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:revoke",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
            metadata={"reason": reason},
        )
        await self.db.commit()
        await self.db.refresh(assertion)
        return assertion

    # ------------------------------------------------------------------
    # Read (S13)
    # ------------------------------------------------------------------

    async def get_assertion(
        self, tenant_id: UUID, assertion_id: UUID
    ) -> BadgeAssertion | None:
        """Fetch a single assertion by id under tenant scope."""
        await set_tenant_context(self.db, str(tenant_id))
        return await self._get_assertion(assertion_id)

    async def list_assertions_for_class(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BadgeAssertion]:
        """List assertions issued from a badge class, newest first."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(BadgeAssertion)
            .where(BadgeAssertion.badge_class_id == badge_class_id)
            .order_by(BadgeAssertion.issued_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_assertions(
        self,
        tenant_id: UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BadgeAssertion]:
        """List all assertions for the tenant, newest first (U6).

        Tenant-scoped via RLS. Optionally filtered by status. Powers the
        issuer-facing Documents list; callers resolve badge-class names with a
        single keyed lookup (no join), mirroring ``WalletService.list_wallet``.
        """
        await set_tenant_context(self.db, str(tenant_id))
        stmt = select(BadgeAssertion)
        if status:
            stmt = stmt.where(BadgeAssertion.status == status)
        stmt = (
            stmt.order_by(BadgeAssertion.issued_at.desc()).limit(limit).offset(offset)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()

    async def _get_assertion(self, assertion_id: UUID) -> BadgeAssertion | None:
        result = await self.db.execute(
            select(BadgeAssertion).where(BadgeAssertion.id == assertion_id)
        )
        return result.scalar_one_or_none()

    async def _notify_issued(
        self, tenant_id: UUID, beneficiary_id: str, assertion_id: UUID, badge_name: str
    ) -> None:
        """Best-effort issuance notification (non-fatal, mirrors document flow)."""
        try:
            from app.services.notification_service import NotificationService

            notifier = NotificationService(db=self.db, settings=self.settings)
            await notifier.notify(
                tenant_id=tenant_id,
                beneficiary_id=beneficiary_id,
                event_type="issuance",
                payload={
                    "assertion_id": str(assertion_id),
                    "badge_name": badge_name,
                    "message": f"You have earned the '{badge_name}' badge.",
                },
            )
        except Exception as exc:
            logger.warning("Badge issuance notification failed (non-fatal): %s", exc)


def new_recipient_salt() -> str:
    """Generate a random salt for hashing a recipient identity in OB output."""
    return secrets.token_hex(16)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IssuanceValidationError(Exception):
    pass


class AssertionNotFoundError(Exception):
    def __init__(self, assertion_id: UUID) -> None:
        self.assertion_id = assertion_id
        super().__init__(f"Assertion not found: {assertion_id}")


class AssertionAlreadyRevokedError(Exception):
    def __init__(self, assertion_id: UUID) -> None:
        self.assertion_id = assertion_id
        super().__init__(f"Assertion already revoked: {assertion_id}")


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_issuance_service(db: AsyncSession = Depends(get_db)) -> IssuanceService:
    return IssuanceService(db=db, settings=get_settings())
