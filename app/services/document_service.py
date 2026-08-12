"""
Document service — upload, retrieval, download, revocation, bulk revoke.

Queries use single-table filters with tenant_id + document ID.
No joins — RLS and direct column filters handle scoping.

Requirements: 3.1, 3.3, 3.4, 3.5, 3.7, 3.11, 4.1-4.9, 6.1-6.7
"""

from __future__ import annotations

import logging
import uuid as uuid_mod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.document import BulkJob, Document
from app.models.schema import DocumentSchema
from app.services.encryption_service import (
    EncryptedPayload,
    EncryptionService,
    EncryptionUnavailableError,
    get_encryption_service,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Successful document upload result."""

    credential_id: str
    status: str


@dataclass(frozen=True, slots=True)
class DocumentMeta:
    """Document metadata returned to callers."""

    credential_id: str
    schema_id: str
    schema_version: int
    beneficiary_id: str
    status: str
    issued_at: str
    revoked_at: str | None
    revocation_reason: str | None


class DocumentService:
    """Handles document upload, retrieval, revocation.

    All queries filter by tenant_id directly — no joins.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._s3 = self._create_s3_client()
        self._encryption = get_encryption_service()

    def _create_s3_client(self):
        kwargs: dict = {"region_name": self.settings.aws_region}
        if self.settings.s3_endpoint_url:
            kwargs["endpoint_url"] = self.settings.s3_endpoint_url
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("s3", **kwargs)

    # ------------------------------------------------------------------
    # Upload (Req 3.1, 3.3, 3.4, 3.5, 3.6, 3.7)
    # ------------------------------------------------------------------

    async def upload_document(
        self,
        tenant_id: UUID,
        schema_id: UUID,
        beneficiary_id: str,
        content: bytes,
        cmk_arn: str,
    ) -> UploadResult:
        """Upload a single document with encryption.

        Validates schema existence and active status.
        Encrypts content and stores to S3.
        No joins — schema lookup is a single query by ID with RLS.
        """
        if not beneficiary_id or not beneficiary_id.strip():
            raise DocumentValidationError("beneficiary_id must be non-empty")

        await set_tenant_context(self.db, str(tenant_id))

        # Validate schema exists and is active (single table query)
        schema_result = await self.db.execute(
            select(DocumentSchema).where(
                DocumentSchema.id == schema_id,
                DocumentSchema.status == "active",
            )
        )
        schema = schema_result.scalar_one_or_none()
        if schema is None:
            raise DocumentValidationError(
                "Schema not found or deactivated. Cannot upload documents."
            )

        # Encrypt content
        try:
            encrypted = self._encryption.encrypt(content, cmk_arn)
        except EncryptionUnavailableError:
            raise ServiceUnavailableError("Encryption service unavailable")

        # Store ciphertext in S3
        credential_id = str(uuid_mod.uuid4())
        s3_key = f"{tenant_id}/{credential_id}"

        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=s3_key,
                Body=encrypted.ciphertext,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("S3 upload failed: %s", exc)
            raise ServiceUnavailableError("Storage service unavailable") from exc

        # Insert document metadata (RLS ensures tenant isolation)
        doc = Document(
            id=UUID(credential_id),
            tenant_id=tenant_id,
            schema_id=schema_id,
            schema_version=schema.version,
            beneficiary_id=beneficiary_id,
            status="stored",
            s3_key=s3_key,
            encrypted_dek=encrypted.encrypted_dek,
            iv=encrypted.iv,
        )
        self.db.add(doc)
        await self.db.commit()

        return UploadResult(credential_id=credential_id, status="stored")

    # ------------------------------------------------------------------
    # Retrieval (Req 4.1, 4.2, 4.3)
    # ------------------------------------------------------------------

    async def get_document(
        self, tenant_id: UUID, credential_id: UUID
    ) -> Document | None:
        """Get document metadata by ID. No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(Document.id == credential_id)
        )
        return result.scalar_one_or_none()

    async def get_document_for_beneficiary(
        self, tenant_id: UUID, credential_id: UUID, beneficiary_id: str
    ) -> Document | None:
        """Get document only if beneficiary matches (Req 4.2, 4.3).

        Returns None for mismatch — caller returns 403 indistinguishable
        from not-found.
        """
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(
                Document.id == credential_id,
                Document.beneficiary_id == beneficiary_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_documents_for_beneficiary(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Document]:
        """List documents for a beneficiary (Req 4.1). No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document)
            .where(Document.beneficiary_id == beneficiary_id)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_documents(
        self, tenant_id: UUID, limit: int = 20, offset: int = 0
    ) -> list[Document]:
        """List all documents for a tenant (issuer/admin view). No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document)
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Download (Req 4.7, 4.8)
    # ------------------------------------------------------------------

    async def download_document(
        self, tenant_id: UUID, credential_id: UUID
    ) -> bytes:
        """Download and decrypt document content. No joins."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(Document.id == credential_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(credential_id)

        # Fetch ciphertext from S3
        try:
            s3_response = self._s3.get_object(
                Bucket=self.settings.s3_bucket_name,
                Key=doc.s3_key,
            )
            ciphertext = s3_response["Body"].read()
        except Exception as exc:
            logger.error("S3 download failed for %s: %s", doc.s3_key, exc)
            raise ServiceUnavailableError("Storage service unavailable") from exc

        # Decrypt
        try:
            decrypted = self._encryption.decrypt(doc.encrypted_dek, doc.iv, ciphertext)
        except EncryptionUnavailableError:
            raise ServiceUnavailableError("Encryption service unavailable")

        return decrypted.plaintext

    # ------------------------------------------------------------------
    # Revocation (Req 6.1, 6.2, 6.4, 6.5)
    # ------------------------------------------------------------------

    async def revoke_document(
        self,
        tenant_id: UUID,
        credential_id: UUID,
        reason: str,
    ) -> Document:
        """Revoke a document (Req 6.1, 6.2). No joins."""
        if not reason or len(reason) > 500:
            raise DocumentValidationError("revocation_reason must be 1-500 characters")

        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(Document.id == credential_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(credential_id)

        if doc.status == "revoked":
            raise DocumentAlreadyRevokedError(credential_id)

        doc.status = "revoked"
        doc.revoked_at = datetime.now(timezone.utc)
        doc.revocation_reason = reason
        await self.db.commit()
        await self.db.refresh(doc)
        return doc

    async def bulk_revoke(
        self,
        tenant_id: UUID,
        credential_ids: list[UUID],
        reason: str,
    ) -> list[dict[str, str]]:
        """Revoke multiple documents independently (Req 6.6, 6.7).

        Returns per-item result. Valid revocations proceed even when
        others in the batch fail. No joins.
        """
        await set_tenant_context(self.db, str(tenant_id))
        results = []
        now = datetime.now(timezone.utc)

        for cid in credential_ids:
            result = await self.db.execute(
                select(Document).where(Document.id == cid)
            )
            doc = result.scalar_one_or_none()

            if doc is None:
                results.append({"credential_id": str(cid), "result": "not-found"})
            elif doc.status == "revoked":
                results.append({"credential_id": str(cid), "result": "already-revoked"})
            else:
                doc.status = "revoked"
                doc.revoked_at = now
                doc.revocation_reason = reason
                results.append({"credential_id": str(cid), "result": "revoked"})

        await self.db.commit()
        return results


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DocumentNotFoundError(Exception):
    def __init__(self, credential_id: UUID) -> None:
        self.credential_id = credential_id
        super().__init__(f"Document not found: {credential_id}")


class DocumentValidationError(Exception):
    pass


class DocumentAlreadyRevokedError(Exception):
    def __init__(self, credential_id: UUID) -> None:
        self.credential_id = credential_id
        super().__init__(f"Document already revoked: {credential_id}")


class ServiceUnavailableError(Exception):
    pass


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_document_service(
    db: AsyncSession = Depends(get_db),
) -> DocumentService:
    return DocumentService(db=db, settings=get_settings())
