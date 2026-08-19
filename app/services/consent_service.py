"""
ConsentService — consent lifecycle and data-principal rights (DPDP Act).

Design decisions worth stating.

*Append-only history.* Withdrawing consent writes a new ``withdrawn`` row rather
than mutating the grant. A disclosure made last month was either authorised at
that moment or it was not, and mutating the record destroys the evidence either
way.

*Consent is resolved, not read.* ``current_consent`` returns the newest record
for a (principal, purpose) pair and treats expiry as withdrawal. Callers ask
"may I do this now?" and get one answer.

*Erasure is requested, not executed inline.* Erasure spans object storage,
per-tenant keys, and backups. It is recorded, acknowledged with a deadline, and
carried out by a worker, so the platform can always show when a request arrived
and what happened to it.

*Erasure has limits, stated explicitly.* Issued credentials may be under a
statutory retention obligation, and anchored Merkle roots are immutable by
construction. Rather than silently partially erasing, a request that cannot be
fully honoured is recorded with a reason. Anchors are unaffected because they
commit to a salted hash, never a raw identifier.

Requirements: 5.x (consent-scoped disclosure), 7.5, 10.4
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.consent import ConsentRecord, ErasureRequest

logger = logging.getLogger(__name__)

# Purposes the platform recognises. Free-text purposes would make consent
# unauditable, so callers must use one of these.
PURPOSE_VERIFICATION = "credential_verification"
PURPOSE_NOTIFICATION = "notification_delivery"
PURPOSE_DIGILOCKER = "digilocker_publication"
PURPOSE_ANALYTICS = "aggregate_analytics"

KNOWN_PURPOSES: frozenset[str] = frozenset(
    {
        PURPOSE_VERIFICATION,
        PURPOSE_NOTIFICATION,
        PURPOSE_DIGILOCKER,
        PURPOSE_ANALYTICS,
    }
)


class ConsentError(Exception):
    """Invalid consent operation."""


class ConsentService:
    """Records and resolves consent, and tracks rights requests."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------
    # Consent lifecycle
    # ------------------------------------------------------------------

    async def grant(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        purpose: str,
        scope: list[str],
        document_id: UUID | None = None,
        legal_basis: str = "consent",
        collected_via: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> ConsentRecord:
        """Record a consent grant."""
        if purpose not in KNOWN_PURPOSES:
            raise ConsentError(
                f"Unknown purpose {purpose!r}. Known purposes: "
                f"{', '.join(sorted(KNOWN_PURPOSES))}"
            )

        await set_tenant_context(self.db, str(tenant_id))
        now = datetime.now(timezone.utc)

        expires_at = None
        if self.settings.consent_default_expiry_days > 0:
            expires_at = now + timedelta(
                days=self.settings.consent_default_expiry_days
            )

        record = ConsentRecord(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            document_id=document_id,
            purpose=purpose,
            legal_basis=legal_basis,
            state="granted",
            scope=scope,
            # Pin the notice version so we can prove what they were shown.
            notice_version=self.settings.consent_notice_version,
            granted_at=now,
            expires_at=expires_at,
            collected_via=collected_via,
            evidence=evidence,
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        logger.info(
            "Consent granted: tenant=%s purpose=%s scope_size=%d",
            tenant_id, purpose, len(scope),
        )
        return record

    async def withdraw(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        purpose: str,
        document_id: UUID | None = None,
    ) -> ConsentRecord | None:
        """Record a withdrawal, returning None if there was nothing to withdraw.

        Writes a new row; the original grant is left intact as evidence of what
        was authorised while it was in force.
        """
        current = await self.current_consent(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            purpose=purpose,
            document_id=document_id,
        )
        if current is None or current.state != "granted":
            return None

        now = datetime.now(timezone.utc)
        record = ConsentRecord(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            document_id=document_id,
            purpose=purpose,
            legal_basis=current.legal_basis,
            state="withdrawn",
            scope=current.scope,
            notice_version=current.notice_version,
            granted_at=current.granted_at,
            withdrawn_at=now,
            collected_via="withdrawal",
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        logger.info(
            "Consent withdrawn: tenant=%s purpose=%s", tenant_id, purpose
        )
        return record

    async def current_consent(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        purpose: str,
        document_id: UUID | None = None,
    ) -> ConsentRecord | None:
        """Return the newest consent record for this purpose, or None.

        A record whose ``expires_at`` has passed is reported as ``expired`` so
        callers never have to reason about timers themselves.
        """
        await set_tenant_context(self.db, str(tenant_id))

        stmt = (
            select(ConsentRecord)
            .where(
                ConsentRecord.tenant_id == tenant_id,
                ConsentRecord.data_principal_id == data_principal_id,
                ConsentRecord.purpose == purpose,
            )
            .order_by(ConsentRecord.created_at.desc())
            .limit(1)
        )
        if document_id is not None:
            stmt = stmt.where(ConsentRecord.document_id == document_id)

        record = (await self.db.execute(stmt)).scalar_one_or_none()
        if record is None:
            return None

        if (
            record.state == "granted"
            and record.expires_at is not None
            and record.expires_at < datetime.now(timezone.utc)
        ):
            record.state = "expired"
        return record

    async def is_allowed(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        purpose: str,
        document_id: UUID | None = None,
    ) -> bool:
        """Return True when processing for *purpose* is currently permitted.

        Statutory bases are permitted regardless of consent state: they are not
        consent and cannot be withdrawn.
        """
        record = await self.current_consent(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            purpose=purpose,
            document_id=document_id,
        )
        if record is None:
            return False
        if record.legal_basis in ("legal_obligation", "legitimate_use"):
            return True
        return record.state == "granted"

    async def consented_scope(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        purpose: str,
        document_id: UUID | None = None,
    ) -> list[str]:
        """Return the fields currently consented to, or an empty list."""
        record = await self.current_consent(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            purpose=purpose,
            document_id=document_id,
        )
        if record is None or record.state != "granted":
            return []
        return list(record.scope or [])

    async def history(
        self, *, tenant_id: UUID, data_principal_id: str, limit: int = 100
    ) -> list[ConsentRecord]:
        """Full consent history — the principal's right to know what they agreed to."""
        await set_tenant_context(self.db, str(tenant_id))
        return list(
            (
                await self.db.execute(
                    select(ConsentRecord)
                    .where(
                        ConsentRecord.tenant_id == tenant_id,
                        ConsentRecord.data_principal_id == data_principal_id,
                    )
                    .order_by(ConsentRecord.created_at.desc())
                    .limit(limit)
                )
            ).scalars().all()
        )

    # ------------------------------------------------------------------
    # Data-principal rights
    # ------------------------------------------------------------------

    async def submit_request(
        self,
        *,
        tenant_id: UUID,
        data_principal_id: str,
        request_type: str,
        details: dict[str, Any] | None = None,
    ) -> ErasureRequest:
        """Record an access, correction, or erasure request."""
        if request_type not in ("erasure", "correction", "access"):
            raise ConsentError(
                f"Unknown request_type {request_type!r}; expected one of "
                "'erasure', 'correction', 'access'"
            )

        await set_tenant_context(self.db, str(tenant_id))

        request = ErasureRequest(
            tenant_id=tenant_id,
            data_principal_id=data_principal_id,
            request_type=request_type,
            state="received",
            details=details,
        )
        self.db.add(request)
        await self.db.commit()
        await self.db.refresh(request)

        logger.info(
            "Rights request received: tenant=%s type=%s id=%s",
            tenant_id, request_type, request.id,
        )
        return request

    async def list_requests(
        self, *, tenant_id: UUID, data_principal_id: str | None = None, limit: int = 100
    ) -> list[ErasureRequest]:
        """List rights requests, optionally for one principal."""
        await set_tenant_context(self.db, str(tenant_id))
        stmt = (
            select(ErasureRequest)
            .where(ErasureRequest.tenant_id == tenant_id)
            .order_by(ErasureRequest.received_at.desc())
            .limit(limit)
        )
        if data_principal_id is not None:
            stmt = stmt.where(ErasureRequest.data_principal_id == data_principal_id)
        return list((await self.db.execute(stmt)).scalars().all())

    def erasure_deadline(self, received_at: datetime) -> datetime:
        """When a recorded erasure request becomes executable."""
        return received_at + timedelta(days=self.settings.erasure_grace_days)

    async def describe_erasure_limits(
        self, *, tenant_id: UUID, data_principal_id: str
    ) -> dict[str, Any]:
        """Explain up front what erasure will and will not remove.

        Telling a principal this before they rely on erasure is more honest than
        accepting the request and partially fulfilling it. Two genuine limits
        apply, and both are consequences of the design rather than choices made
        per request.
        """
        from app.models.document import Document
        from app.models.tenant import Tenant

        await set_tenant_context(self.db, str(tenant_id))

        doc_count = (
            await self.db.execute(
                select(Document.id).where(
                    Document.tenant_id == tenant_id,
                    Document.beneficiary_id == data_principal_id,
                )
            )
        ).scalars().all()

        retention_years = (
            await self.db.execute(
                select(Tenant.retention_years).where(Tenant.id == tenant_id)
            )
        ).scalar_one_or_none()

        return {
            "documents_held": len(doc_count),
            "tenant_retention_years": retention_years,
            "will_be_erased": [
                "Notification contact details (email, phone)",
                "Consent records beyond the statutory audit minimum",
                "Verification tokens and their consented-field lists",
            ],
            "cannot_be_erased": [
                {
                    "item": "Issued credentials still within the retention period",
                    "reason": (
                        "Retained under the issuing authority's statutory "
                        f"retention obligation ({retention_years} years). They are "
                        "purged automatically when that period elapses."
                    ),
                },
                {
                    "item": "Audit log entries",
                    "reason": (
                        "Immutable by database trigger and required to evidence "
                        "lawful processing, including this erasure request itself."
                    ),
                },
                {
                    "item": "Ledger anchors",
                    "reason": (
                        "Anchors commit to a salted hash, never a personal "
                        "identifier, so they contain no erasable personal data. "
                        "They cannot be altered and do not need to be."
                    ),
                },
            ],
            "grievance_officer_email": self.settings.grievance_officer_email or None,
        }


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_consent_service(
    db: AsyncSession = Depends(get_db),
) -> ConsentService:
    """Provide a ConsentService for route handlers."""
    return ConsentService(db=db, settings=get_settings())
