"""
Verification token service — generation, consumption, public verification.

All queries use single-table lookups by token_hash or document_id.
No joins needed.

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 6.3
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.document import Document
from app.models.verification import VerificationToken

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TokenGenerationResult:
    """Result of generating a verification token."""

    token: str  # The raw token (given to beneficiary, never stored)
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Result of consuming a verification token."""

    valid: bool
    status: str  # "valid", "revoked", "invalid", "expired", "used"
    issuer_name: str | None
    issued_at: str | None
    fields: dict[str, Any] | None
    revoked_at: str | None


class VerificationService:
    """Manages verification token lifecycle. No joins — single table lookups."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()

    async def generate_token(
        self,
        tenant_id: UUID,
        document_id: UUID,
        beneficiary_id: str,
        consented_fields: list[str],
        expiry_hours: int | None = None,
    ) -> TokenGenerationResult:
        """Generate a verification token for a document (Req 5.1).

        The beneficiary must own the document. Token is cryptographically
        random; only its SHA-256 hash is stored.
        """
        hours = expiry_hours or self.settings.verification_token_default_expiry_hours
        if not (1 <= hours <= self.settings.verification_token_max_expiry_hours):
            raise VerificationError(
                f"expiry_hours must be between 1 and {self.settings.verification_token_max_expiry_hours}"
            )

        await set_tenant_context(self.db, str(tenant_id))

        # Verify document belongs to beneficiary (single table query)
        result = await self.db.execute(
            select(Document).where(
                Document.id == document_id,
                Document.beneficiary_id == beneficiary_id,
            )
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise VerificationError("Document not found or does not belong to beneficiary")

        # Generate cryptographically random token
        raw_token = urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

        vt = VerificationToken(
            tenant_id=tenant_id,
            document_id=document_id,
            token_hash=token_hash,
            consented_fields=consented_fields,
            expires_at=expires_at,
        )
        self.db.add(vt)
        await self.db.commit()

        return TokenGenerationResult(token=raw_token, expires_at=expires_at)

    async def consume_token(self, raw_token: str) -> VerificationResult:
        """Consume a verification token (Req 5.2, 5.3, 5.4, 5.5).

        Single-use: marks used_at atomically.
        No joins — looks up token by hash, then document by ID.
        """
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

        # Look up token (no tenant context needed — unique hash)
        result = await self.db.execute(
            select(VerificationToken).where(VerificationToken.token_hash == token_hash)
        )
        vt = result.scalar_one_or_none()

        if vt is None:
            return VerificationResult(
                valid=False, status="invalid",
                issuer_name=None, issued_at=None, fields=None, revoked_at=None,
            )

        if vt.used_at is not None:
            return VerificationResult(
                valid=False, status="used",
                issuer_name=None, issued_at=None, fields=None, revoked_at=None,
            )

        now = datetime.now(timezone.utc)
        if vt.expires_at < now:
            return VerificationResult(
                valid=False, status="expired",
                issuer_name=None, issued_at=None, fields=None, revoked_at=None,
            )

        # Mark as used atomically
        vt.used_at = now
        await self.db.flush()

        # Fetch document (single table query by ID)
        doc_result = await self.db.execute(
            select(Document).where(Document.id == vt.document_id)
        )
        doc = doc_result.scalar_one_or_none()

        if doc is None:
            await self.db.commit()
            return VerificationResult(
                valid=False, status="invalid",
                issuer_name=None, issued_at=None, fields=None, revoked_at=None,
            )

        # Build consented field data (would come from document metadata in full impl)
        fields = {f: f"[{f}]" for f in (vt.consented_fields or [])} if vt.consented_fields else None

        status = "revoked" if doc.status == "revoked" else "valid"
        revoked_at = doc.revoked_at.isoformat() if doc.revoked_at else None

        await self.db.commit()

        return VerificationResult(
            valid=(status == "valid"),
            status=status,
            issuer_name=str(doc.tenant_id),  # In full impl: fetch tenant name
            issued_at=doc.created_at.isoformat() if doc.created_at else None,
            fields=fields,
            revoked_at=revoked_at,
        )

    async def verify_credential_public(self, credential_id: UUID) -> dict[str, str]:
        """Public verification — returns only validity status (Req 5.6, 5.10).

        No auth required. No document fields. No joins.
        """
        result = await self.db.execute(
            select(Document.status).where(Document.id == credential_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return {"status": "invalid"}
        if row == "revoked":
            return {"status": "revoked"}
        return {"status": "valid"}


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class VerificationError(Exception):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_verification_service(db: AsyncSession = Depends(get_db)) -> VerificationService:
    return VerificationService(db=db)
