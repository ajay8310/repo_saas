"""
Document service — upload, retrieval, download, revocation, bulk revoke.

Queries use single-table filters with tenant_id + document ID.
No joins — RLS and direct column filters handle scoping.

Wires: malware scan → encryption → S3 → audit → notification → webhook → DigiLocker.

Requirements: 3.1, 3.3, 3.4, 3.5, 3.7, 3.11, 4.1-4.9, 6.1-6.7
"""

from __future__ import annotations

import hashlib
import json
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
from app.models.tenant import Tenant
from app.services.audit_service import AuditService
from app.services.encryption_service import (
    EncryptedPayload,
    EncryptionService,
    EncryptionUnavailableError,
    get_encryption_service,
)
from app.services.malware_scanner import (
    MalwareScanner,
    ScanUnavailableError,
    get_malware_scanner,
)

logger = logging.getLogger(__name__)

# Accepted values for the download `format` parameter (Req 4.7).
_DOWNLOAD_FORMATS = {"raw", "pdf", "jsonld"}


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Successful document upload result."""

    credential_id: str
    status: str


@dataclass(frozen=True, slots=True)
class RenderedDocument:
    """A download payload plus the metadata needed to serve it."""

    content: bytes
    media_type: str
    filename: str


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
    Wires: malware scan → encryption → S3 → DB → audit → notification → webhook → DigiLocker.
    """

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._s3 = self._create_s3_client()
        self._encryption = get_encryption_service()
        self._audit = AuditService(db)
        self._scanner: MalwareScanner | None = None

    @property
    def scanner(self) -> MalwareScanner:
        if self._scanner is None:
            self._scanner = get_malware_scanner()
        return self._scanner

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
        cmk_arn: str | None = None,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> UploadResult:
        """Upload a single document with full pipeline.

        Flow: validate → malware scan → encrypt → S3 → DB insert → audit → events.
        No joins — schema lookup is a single query by ID with RLS.
        """
        if not beneficiary_id or not beneficiary_id.strip():
            raise DocumentValidationError("beneficiary_id must be non-empty")

        await set_tenant_context(self.db, str(tenant_id))

        # 1. Validate schema exists and is active (single table query)
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

        # 2. Malware scan — never bypass (Req 13.5)
        try:
            scan_result = self.scanner.scan(content)
            if not scan_result.clean:
                raise DocumentValidationError(
                    f"File rejected: malware detected ({scan_result.reason})"
                )
        except ScanUnavailableError:
            raise ServiceUnavailableError(
                "Malware scan service unavailable. Upload rejected."
            )

        # 3. Encrypt content (Req 3.6).
        # The CMK is resolved from the tenant's own key record, not taken from
        # the caller. Accepting a client-supplied ARN let a tenant point
        # encryption at any key they could name — including one they control,
        # which would hand them the plaintext DEK for their own documents.
        resolved_cmk = await self._resolve_cmk(tenant_id, cmk_arn)
        try:
            encrypted = self._encryption.encrypt(content, resolved_cmk)
        except EncryptionUnavailableError:
            raise ServiceUnavailableError("Encryption service unavailable")

        # 4. Store ciphertext in S3
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

        # 5. Insert document metadata (RLS ensures tenant isolation)
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

        # 6. Audit log — same transaction (Req 3.5, 10.7)
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="document:upload",
            resource_type="document",
            resource_id=credential_id,
            outcome="success",
            metadata={"schema_id": str(schema_id), "beneficiary_id": beneficiary_id},
        )

        await self.db.commit()

        # 7. Commit the credential to the anchoring batch. Recorded here rather
        # than in the batch sweep so the digest is fixed at issuance time, and
        # over the plaintext hash rather than the ciphertext so key rotation
        # cannot invalidate historical proofs.
        try:
            from app.services.anchoring import AnchoringService

            await self.db.refresh(doc)
            anchoring = AnchoringService(db=self.db, settings=self.settings)
            await anchoring.record_document(
                tenant_id=tenant_id,
                document=doc,
                content_sha256=hashlib.sha256(content).hexdigest(),
            )
        except Exception:
            # A missing anchor is recoverable (the sweep can backfill it); a
            # failed issuance is not.
            logger.exception(
                "Could not record anchor commitment for %s", credential_id
            )

        # 8. Fire-and-forget async events (notifications, webhooks, DigiLocker)
        await self._dispatch_upload_events(tenant_id, credential_id, beneficiary_id)

        return UploadResult(credential_id=credential_id, status="stored")

    async def _resolve_cmk(self, tenant_id: UUID, requested: str | None) -> str:
        """Return the tenant's active CMK ARN.

        A caller-supplied value is honoured only when it matches a key actually
        registered to this tenant. That keeps the parameter usable for key
        rotation (targeting a specific registered key) while refusing an
        arbitrary ARN.
        """
        from app.models.tenant import TenantEncryptionKey

        await set_tenant_context(self.db, str(tenant_id))
        rows = (
            await self.db.execute(
                select(TenantEncryptionKey).where(
                    TenantEncryptionKey.tenant_id == tenant_id,
                    TenantEncryptionKey.status.in_(("active", "pending_rotation")),
                )
            )
        ).scalars().all()

        if not rows:
            raise ServiceUnavailableError(
                "No encryption key is provisioned for this tenant. Provision a "
                "CMK before issuing documents."
            )

        if requested:
            if any(k.kms_key_arn == requested for k in rows):
                return requested
            raise DocumentValidationError(
                "cmk_arn is not a key registered to this tenant."
            )

        active = next((k for k in rows if k.status == "active"), rows[0])
        return active.kms_key_arn

    async def _dispatch_upload_events(
        self, tenant_id: UUID, credential_id: str, beneficiary_id: str
    ) -> None:
        """Dispatch post-upload events (best effort, non-blocking)."""
        try:
            from app.services.notification_service import NotificationService
            from app.services.webhook_service import WebhookService
            from app.services.digilocker_connector import DigiLockerConnector

            # Notification to beneficiary
            notifier = NotificationService(db=self.db, settings=self.settings)
            await notifier.notify(
                tenant_id=tenant_id,
                beneficiary_id=beneficiary_id,
                event_type="issuance",
                payload={"credential_id": credential_id, "message": "A new document has been issued to you."},
            )

            # Webhook dispatch writes pending event rows...
            webhook_svc = WebhookService(db=self.db)
            event_ids = await webhook_svc.dispatch_event(
                tenant_id=tenant_id,
                event_type="document.uploaded",
                payload={"credential_id": credential_id, "beneficiary_id": beneficiary_id},
            )

            # ...and the worker actually delivers them. Without this the rows
            # sat at 'pending' forever, since deliver_event had no caller.
            from app.tasks.dispatch import (
                enqueue_digilocker_push,
                enqueue_webhook_delivery,
            )

            for event_id in event_ids:
                enqueue_webhook_delivery(str(event_id))

            # DigiLocker push: record intent, then ask the worker to attempt it.
            dl_connector = DigiLockerConnector(db=self.db, settings=self.settings)
            push = await dl_connector.enqueue_push(
                tenant_id=tenant_id,
                document_id=UUID(credential_id),
            )
            enqueue_digilocker_push(str(push.id))
        except Exception as exc:
            # Events are best-effort; don't fail the upload
            logger.warning("Post-upload event dispatch error (non-fatal): %s", exc)

    # ------------------------------------------------------------------
    # Retrieval (Req 4.1, 4.2, 4.3)
    # ------------------------------------------------------------------

    async def get_document(
        self, tenant_id: UUID, credential_id: UUID,
        actor_id: str = "system", actor_role: str = "issuer",
    ) -> Document | None:
        """Get document metadata by ID. No joins. Logs access attempt."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(Document.id == credential_id)
        )
        doc = result.scalar_one_or_none()

        # Audit every retrieval attempt (Req 4.9, 10.1)
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="document:read",
            resource_type="document",
            resource_id=str(credential_id),
            outcome="success" if doc else "not_found",
        )
        await self.db.commit()
        return doc

    async def get_document_for_beneficiary(
        self, tenant_id: UUID, credential_id: UUID, beneficiary_id: str,
        actor_id: str = "system", actor_role: str = "beneficiary",
    ) -> Document | None:
        """Get document only if beneficiary matches (Req 4.2, 4.3).

        Returns None for mismatch — caller returns 403 indistinguishable
        from not-found. Logs access attempt.
        """
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(
                Document.id == credential_id,
                Document.beneficiary_id == beneficiary_id,
            )
        )
        doc = result.scalar_one_or_none()

        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="document:read",
            resource_type="document",
            resource_id=str(credential_id),
            outcome="success" if doc else "denied",
        )
        await self.db.commit()
        return doc

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
        self,
        tenant_id: UUID,
        credential_id: UUID,
        output_format: str = "raw",
        actor_id: str = "system",
        actor_role: str = "beneficiary",
    ) -> RenderedDocument:
        """Download a document, optionally rendered as PDF or JSON-LD (Req 4.7).

        ``output_format`` is one of ``raw`` | ``pdf`` | ``jsonld``. The rendered
        formats embed the credential ID, a QR code pointing at the public
        verification URL, and an RS256 proof over the credential payload.

        Every attempt is audited (Req 4.9). Queries are single-table lookups by
        primary key — no joins.
        """
        if output_format not in _DOWNLOAD_FORMATS:
            raise DocumentValidationError(
                f"format must be one of: {', '.join(sorted(_DOWNLOAD_FORMATS))}"
            )

        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(Document).where(Document.id == credential_id)
        )
        doc = result.scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(credential_id)

        # Audit the download (Req 4.9)
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="document:download",
            resource_type="document",
            resource_id=str(credential_id),
            outcome="success",
            metadata={"format": output_format},
        )
        await self.db.commit()

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

        plaintext = decrypted.plaintext

        if output_format == "raw":
            return RenderedDocument(
                content=plaintext,
                media_type="application/octet-stream",
                filename=f"{credential_id}.bin",
            )

        ctx = await self._build_render_context(doc, plaintext)

        from app.services.document_renderer import render_json_ld, render_pdf

        if output_format == "pdf":
            return RenderedDocument(
                content=render_pdf(ctx),
                media_type="application/pdf",
                filename=f"{credential_id}.pdf",
            )

        return RenderedDocument(
            content=render_json_ld(ctx),
            media_type="application/ld+json",
            filename=f"{credential_id}.jsonld",
        )

    async def _build_render_context(self, doc: Document, plaintext: bytes):
        """Assemble the data the renderers need.

        Two single-table primary-key lookups (tenant name, schema name) rather
        than a join. Field values come from the decrypted payload when it is a
        JSON object; non-JSON content renders with an empty field table.
        """
        from app.services.document_renderer import RenderContext

        tenant_result = await self.db.execute(
            select(Tenant.name).where(Tenant.id == doc.tenant_id)
        )
        issuer_name = tenant_result.scalar_one_or_none() or "Unknown Issuer"

        schema_result = await self.db.execute(
            select(DocumentSchema.name).where(DocumentSchema.id == doc.schema_id)
        )
        schema_name = schema_result.scalar_one_or_none() or "Credential"

        fields: dict[str, Any] = {}
        try:
            parsed = json.loads(plaintext.decode("utf-8"))
            if isinstance(parsed, dict):
                fields = parsed
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.debug(
                "Document %s payload is not JSON; rendering without field table",
                doc.id,
            )

        return RenderContext(
            credential_id=str(doc.id),
            issuer_name=issuer_name,
            schema_name=schema_name,
            schema_version=doc.schema_version,
            beneficiary_id=doc.beneficiary_id,
            issued_at=doc.issued_at.isoformat() if doc.issued_at else "",
            status=doc.status,
            revoked_at=doc.revoked_at.isoformat() if doc.revoked_at else None,
            revocation_reason=doc.revocation_reason,
            fields=fields,
        )

    # ------------------------------------------------------------------
    # Revocation (Req 6.1, 6.2, 6.4, 6.5)
    # ------------------------------------------------------------------

    async def revoke_document(
        self,
        tenant_id: UUID,
        credential_id: UUID,
        reason: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> Document:
        """Revoke a document (Req 6.1, 6.2). Logs audit + notifies beneficiary."""
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

        # Audit log — same transaction (Req 10.7)
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="document:revoke",
            resource_type="document",
            resource_id=str(credential_id),
            outcome="success",
            metadata={"reason": reason},
        )

        await self.db.commit()
        await self.db.refresh(doc)

        # Post-revocation events (best-effort)
        try:
            from app.services.notification_service import NotificationService
            from app.services.webhook_service import WebhookService
            from app.tasks.dispatch import enqueue_webhook_delivery

            notifier = NotificationService(db=self.db, settings=self.settings)
            await notifier.notify(
                tenant_id=tenant_id,
                beneficiary_id=doc.beneficiary_id,
                event_type="revocation",
                payload={"credential_id": str(credential_id), "reason": reason,
                         "message": "One of your documents has been revoked."},
            )

            webhook_svc = WebhookService(db=self.db)
            event_ids = await webhook_svc.dispatch_event(
                tenant_id=tenant_id,
                event_type="document.revoked",
                payload={"credential_id": str(credential_id), "reason": reason},
            )
            for event_id in event_ids:
                enqueue_webhook_delivery(str(event_id))
        except Exception as exc:
            logger.warning("Post-revocation event dispatch error (non-fatal): %s", exc)

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
