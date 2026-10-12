"""Certificate orchestration (U4).

Ties together the pieces needed to produce a downloadable, issuer-signed
certificate PDF for a badge assertion, and to attach a recipient photo:

1. resolve the assertion + its badge class (ownership-checked for earners),
2. fetch the badge image and recipient photo from S3 (best effort),
3. ensure the tenant's issuer signing keypair and sign the credential payload,
4. render the PDF with the class's chosen template, and
5. audit + record a ``viewed`` analytics event.

Follows the established service conventions: RLS via ``set_tenant_context``, a
boto3 S3 client built like ``DocumentService``, malware scanning on upload, and
audit entries inside the transaction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid as uuid_mod
from dataclasses import dataclass
from uuid import UUID

import boto3
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.models.certificate_template import CertificateTemplate
from app.models.tenant import Tenant
from app.services.audit_service import AuditService
from app.services.badge_baker import BadgeImageNotBakeableError, bake_png
from app.services.badge_event_service import BadgeEventService
from app.services.certificate_renderer import (
    CertificateContext,
    CustomAssets,
    render_certificate,
    render_custom_certificate,
)
from app.services.issuer_signing_service import IssuerSigningService
from app.services.malware_scanner import (
    MalwareScanner,
    ScanUnavailableError,
    get_malware_scanner,
)
from app.services.openbadges import (
    AssertionData,
    BadgeClassData,
    IssuerProfile,
    OpenBadgesSerializer,
)

logger = logging.getLogger(__name__)

_ALLOWED_PHOTO_TYPES: frozenset[str] = frozenset(
    {"image/png", "image/jpeg", "image/jpg"}
)


@dataclass(frozen=True, slots=True)
class RenderedCertificate:
    content: bytes
    media_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class RenderedBadge:
    """A downloadable Open Badges artifact (baked PNG or assertion JSON)."""

    content: bytes
    media_type: str
    filename: str


class CertificateService:
    """Build badge certificates and manage recipient photos."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._audit = AuditService(db)
        self._events = BadgeEventService(db)
        self._signing = IssuerSigningService(db, settings)
        self._s3 = self._create_s3_client()
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
    # Recipient photo upload (Q6)
    # ------------------------------------------------------------------

    async def upload_recipient_photo(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        content: bytes,
        content_type: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> str:
        """Scan, store, and attach a recipient photo. Returns the S3 key."""
        if content_type not in _ALLOWED_PHOTO_TYPES:
            raise CertificateValidationError(
                f"photo content_type must be one of {sorted(_ALLOWED_PHOTO_TYPES)}"
            )
        if not content:
            raise CertificateValidationError("photo content must be non-empty")
        if len(content) > self.settings.certificate_photo_max_bytes:
            raise CertificateValidationError("photo exceeds the maximum allowed size")

        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)

        try:
            scan = self.scanner.scan(content)
            if not scan.clean:
                raise CertificateValidationError(f"photo rejected: malware ({scan.reason})")
        except ScanUnavailableError:
            raise CertificateServiceUnavailableError("Malware scan service unavailable")

        ext = "png" if content_type == "image/png" else "jpg"
        s3_key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/"
            f"{assertion.badge_class_id}/photos/{assertion_id}-{uuid_mod.uuid4()}.{ext}"
        )
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=s3_key,
                Body=content,
                ContentType=content_type,
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Recipient photo S3 upload failed: %s", exc)
            raise CertificateServiceUnavailableError("Storage service unavailable") from exc

        assertion.recipient_photo_s3_key = s3_key
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:photo_upload",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
        )
        await self.db.commit()
        return s3_key

    # ------------------------------------------------------------------
    # Bring-your-own certificate PDF (tenant-supplied, pre-built design)
    # ------------------------------------------------------------------

    def presign_certificate_pdf(self, tenant_id: UUID, size_bytes: int) -> tuple[str, str]:
        """Return a presigned PUT URL + upload key for a direct-to-S3 PDF upload.

        Enforces the max PDF size before issuing the URL (re-checked server-side
        when the object is read). The key lives under a per-upload prefix so a
        failed/abandoned upload is easy to reap.
        """
        if size_bytes <= 0:
            raise CertificateValidationError("file size must be greater than zero")
        if size_bytes > self.settings.certificate_pdf_max_bytes:
            raise CertificateValidationError(
                f"PDF exceeds the maximum of {self.settings.certificate_pdf_max_bytes} bytes"
            )
        upload_id = uuid_mod.uuid4()
        key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/_pdf_uploads/"
            f"{upload_id}/certificate.pdf"
        )
        try:
            # Presign against the browser-reachable endpoint when configured, so
            # the URL's signed Host matches what the browser actually PUTs to.
            # (The internal 'localstack' host is not resolvable from the host
            # machine; use 'localhost' there via s3_public_endpoint_url.)
            presigner = self._presign_s3_client()
            url = presigner.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.settings.s3_bucket_name,
                    "Key": key,
                    "ContentType": "application/pdf",
                    "ServerSideEncryption": "aws:kms",
                },
                ExpiresIn=self.settings.certificate_pdf_presign_ttl_seconds,
            )
        except Exception as exc:
            logger.error("Certificate PDF presign failed: %s", exc)
            raise CertificateServiceUnavailableError("Storage service unavailable") from exc
        return url, key

    def _presign_s3_client(self):
        """An S3 client whose endpoint is the browser-reachable public endpoint.

        Falls back to the normal internal client when no public endpoint is set
        (e.g. real AWS, where the regional endpoint is reachable everywhere).
        """
        public = self.settings.s3_public_endpoint_url
        if not public:
            return self._s3
        kwargs: dict = {"region_name": self.settings.aws_region, "endpoint_url": public}
        if self.settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = self.settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = self.settings.aws_secret_access_key
        return boto3.client("s3", **kwargs)

    async def attach_certificate_pdf_from_key(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        pdf_key: str,
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> tuple[str, str]:
        """Read an uploaded PDF from its upload key, scan, sign, and attach it.

        Reads the tenant-scoped upload object, malware-scans it (fail-closed),
        digitally signs it with the tenant's issuer key (RS256 JWS over the PDF's
        SHA-256), stores it at a permanent key (SSE-KMS), records the signature +
        hash on the assertion, and deletes the temporary upload object. Returns
        ``(permanent_s3_key, pdf_sha256)``.
        """
        prefix = f"{self.settings.badge_image_prefix}/{tenant_id}/_pdf_uploads/"
        if not pdf_key.startswith(prefix) or ".." in pdf_key:
            raise CertificateValidationError("invalid upload key for this tenant")

        try:
            head = self._s3.head_object(Bucket=self.settings.s3_bucket_name, Key=pdf_key)
        except Exception as exc:
            raise CertificateValidationError(
                "uploaded PDF not found — re-upload and try again"
            ) from exc
        if head.get("ContentLength", 0) > self.settings.certificate_pdf_max_bytes:
            self._delete_quiet(pdf_key)
            raise CertificateValidationError("PDF exceeds the maximum allowed size")

        content = self._fetch_s3(pdf_key)
        if not content:
            raise CertificateServiceUnavailableError("Storage service unavailable")
        try:
            return await self.attach_certificate_pdf(
                tenant_id=tenant_id,
                assertion_id=assertion_id,
                content=content,
                content_type="application/pdf",
                actor_id=actor_id,
                actor_role=actor_role,
            )
        finally:
            self._delete_quiet(pdf_key)

    async def attach_certificate_pdf(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        content: bytes,
        content_type: str = "application/pdf",
        actor_id: str = "system",
        actor_role: str = "issuer",
    ) -> tuple[str, str]:
        """Scan, digitally sign, store, and attach a tenant-supplied certificate PDF.

        The PDF is left byte-for-byte unmodified; the signature is an RS256 JWS
        over the PDF's SHA-256, produced with the tenant's issuer key and recorded
        on the assertion (consistent with the platform's JWS signing posture).
        Returns ``(permanent_s3_key, pdf_sha256)``.
        """
        if content_type != "application/pdf":
            raise CertificateValidationError("certificate must be a PDF (application/pdf)")
        if not content:
            raise CertificateValidationError("PDF content must be non-empty")
        if len(content) > self.settings.certificate_pdf_max_bytes:
            raise CertificateValidationError("PDF exceeds the maximum allowed size")
        # Structural sanity: per the PDF spec the %PDF- header may appear within
        # the first 1024 bytes (some exporters prepend a UTF-8 BOM or
        # whitespace), so don't require it at byte 0.
        if b"%PDF-" not in content[:1024]:
            raise CertificateValidationError("file does not look like a valid PDF")

        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)

        try:
            scan = self.scanner.scan(content)
            if not scan.clean:
                raise CertificateValidationError(f"PDF rejected: malware ({scan.reason})")
        except ScanUnavailableError:
            raise CertificateServiceUnavailableError("Malware scan service unavailable")

        tenant = await self._get_tenant(tenant_id)
        issuer_name = (
            tenant.issuer_name if tenant and tenant.issuer_name
            else (tenant.name if tenant else "")
        )

        # Embed a true PAdES digital signature into the PDF using the tenant's
        # X.509 signing cert, so the stored/downloaded PDF carries a signature a
        # PDF viewer can validate. On any signing failure we fall back to the
        # unsigned bytes (the JWS-over-hash below still provides an API-level
        # proof) rather than failing the whole issuance.
        signed = content
        pdf_signed = False
        if self.settings.certificate_pdf_pades_enabled:
            try:
                import asyncio as _asyncio
                import functools as _functools

                from app.services.pdf_signer import PdfSignError, sign_pdf_pades

                private_pem, cert_pem = await self._signing.signing_material(tenant_id)
                # pyHanko's sync sign_pdf internally calls asyncio.run(), which
                # cannot run inside this request's event loop — run it in a
                # worker thread so it gets its own loop.
                signed = await _asyncio.to_thread(
                    _functools.partial(
                        sign_pdf_pades,
                        content,
                        private_key_pem=private_pem,
                        cert_pem=cert_pem,
                        reason="Issued and signed by the credential issuer",
                        location=issuer_name,
                    )
                )
                pdf_signed = True
            except PdfSignError as exc:
                logger.warning(
                    "PAdES signing failed for assertion %s; storing unsigned PDF: %s",
                    assertion_id, exc,
                )
                signed = content

        # Record a JWS over the (signed) PDF's SHA-256 — a verifiable, API-level
        # attestation that complements the embedded signature.
        pdf_sha256 = hashlib.sha256(signed).hexdigest()
        signature_payload = {
            "assertion_id": str(assertion_id),
            "pdf_sha256": pdf_sha256,
            "pdf_signed": pdf_signed,
            "issuer": issuer_name,
            "issued_at": assertion.issued_at.isoformat() if assertion.issued_at else "",
        }
        signature_jws = await self._signing.sign(tenant_id, signature_payload)

        s3_key = (
            f"{self.settings.badge_image_prefix}/{tenant_id}/"
            f"{assertion.badge_class_id}/certificates/{assertion_id}-{uuid_mod.uuid4()}.pdf"
        )
        try:
            self._s3.put_object(
                Bucket=self.settings.s3_bucket_name,
                Key=s3_key,
                Body=signed,
                ContentType="application/pdf",
                ServerSideEncryption="aws:kms",
            )
        except Exception as exc:
            logger.error("Certificate PDF S3 upload failed: %s", exc)
            raise CertificateServiceUnavailableError("Storage service unavailable") from exc

        assertion.certificate_pdf_s3_key = s3_key
        assertion.certificate_pdf_sha256 = pdf_sha256
        assertion.certificate_pdf_signature_jws = signature_jws
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:certificate_pdf_attach",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
            metadata={"pdf_sha256": pdf_sha256, "pdf_signed": pdf_signed},
        )
        await self.db.commit()
        return s3_key, pdf_sha256

    def _delete_quiet(self, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=self.settings.s3_bucket_name, Key=key)
        except Exception:
            logger.debug("Could not delete uploaded PDF %s", key, exc_info=True)

    # ------------------------------------------------------------------
    # Certificate build (Q3/Q4/Q5/Q7)
    # ------------------------------------------------------------------

    async def build_certificate(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        actor_id: str = "system",
        actor_role: str = "issuer",
        require_owner: str | None = None,
    ) -> RenderedCertificate:
        """Render an issuer-signed certificate PDF for an assertion.

        ``require_owner`` (the earner's identity) restricts the download to the
        owning beneficiary; None means an issuer/admin download. Returns 404-like
        errors when the assertion is missing or not owned.
        """
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)
        if require_owner is not None and assertion.beneficiary_id != require_owner:
            raise CertificateNotFoundError(assertion_id)

        # Bring-your-own PDF: a tenant-supplied, pre-built, already-signed
        # certificate takes precedence over template rendering. Return the
        # stored bytes verbatim; still record the view event + audit.
        if assertion.certificate_pdf_s3_key:
            stored = self._fetch_s3(assertion.certificate_pdf_s3_key)
            if stored:
                self._events.record(
                    tenant_id=tenant_id,
                    event_type="viewed",
                    badge_class_id=assertion.badge_class_id,
                    assertion_id=assertion_id,
                    channel="certificate",
                )
                await self._audit.record(
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                    actor_role=actor_role,
                    operation="badge:certificate_download",
                    resource_type="badge_assertion",
                    resource_id=str(assertion_id),
                    outcome="success",
                    metadata={"template": "byo_pdf"},
                )
                await self.db.commit()
                return RenderedCertificate(
                    content=stored,
                    media_type="application/pdf",
                    filename=f"certificate-{assertion_id}.pdf",
                )
            # If the stored object is unexpectedly missing, fall through to
            # render a template so the download never hard-fails.
            logger.warning(
                "BYO certificate PDF missing for assertion %s; falling back to render",
                assertion_id,
            )

        badge_class = await self._get_class(assertion.badge_class_id)
        tenant = await self._get_tenant(tenant_id)

        # Images (best effort — a missing image just renders without it).
        badge_image = (
            self._fetch_s3(badge_class.image_s3_key) if badge_class and badge_class.image_s3_key else None
        )
        recipient_photo = (
            self._fetch_s3(assertion.recipient_photo_s3_key)
            if assertion.recipient_photo_s3_key
            else None
        )

        verify_url = (
            f"{self.settings.public_base_url}"
            f"/api/v1/public/badges/assertions/{assertion_id}"
        )

        # Sign the credential payload with the issuer's own key (Q7).
        payload = {
            "assertion_id": str(assertion_id),
            "badge": badge_class.name if badge_class else "",
            "recipient": _mask_identity(assertion.beneficiary_id),
            "issuer": tenant.issuer_name if tenant and tenant.issuer_name else (tenant.name if tenant else ""),
            "issued_at": assertion.issued_at.isoformat() if assertion.issued_at else "",
            "status": assertion.status,
        }
        signature = await self._signing.sign(tenant_id, payload)

        ctx = CertificateContext(
            assertion_id=str(assertion_id),
            badge_name=badge_class.name if badge_class else "Badge",
            recipient_display=_mask_identity(assertion.beneficiary_id),
            issuer_name=(tenant.issuer_name if tenant and tenant.issuer_name else (tenant.name if tenant else "Issuer")),
            issued_at=assertion.issued_at.isoformat() if assertion.issued_at else "",
            expires_at=assertion.expires_at.isoformat() if assertion.expires_at else None,
            criteria=badge_class.criteria_narrative if badge_class else None,
            verify_url=verify_url,
            signature_jws=signature,
            status=assertion.status,
            revoked_at=assertion.revoked_at.isoformat() if assertion.revoked_at else None,
            revocation_reason=assertion.revocation_reason,
            badge_image=badge_image,
            recipient_photo=recipient_photo,
        )

        # Custom (issuer-designed) template takes precedence over the built-in
        # string when a badge class references one (U5). Any failure in the
        # custom path falls back to the built-in renderer inside
        # render_custom_certificate, so a download never 500s.
        custom_id = getattr(badge_class, "custom_template_id", None) if badge_class else None
        if custom_id is not None:
            template_label, pdf = await self._render_with_custom_template(custom_id, ctx)
        else:
            template_label = (
                badge_class.certificate_template
                if badge_class
                else self.settings.certificate_default_template
            )
            pdf = render_certificate(ctx, template_label)
        template = template_label

        self._events.record(
            tenant_id=tenant_id,
            event_type="viewed",
            badge_class_id=assertion.badge_class_id,
            assertion_id=assertion_id,
            channel="certificate",
        )
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:certificate_download",
            resource_type="badge_assertion",
            resource_id=str(assertion_id),
            outcome="success",
            metadata={"template": template},
        )
        await self.db.commit()

        return RenderedCertificate(
            content=pdf,
            media_type="application/pdf",
            filename=f"certificate-{assertion_id}.pdf",
        )

    # ------------------------------------------------------------------
    # Badge downloads — OB2.0 JSON + baked PNG (U6)
    # ------------------------------------------------------------------

    async def build_badge_json(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        actor_id: str = "system",
        actor_role: str = "issuer",
        require_owner: str | None = None,
    ) -> RenderedBadge:
        """Build the Open Badges 2.0 Assertion JSON for an assertion (U6).

        Authenticated + tenant-scoped (does NOT require the assertion to be
        public, unlike the hosted public endpoint). ``require_owner`` restricts
        to the owning beneficiary. Always succeeds for a resolvable assertion.
        """
        assertion, badge_class, tenant = await self._resolve_for_badge(
            tenant_id, assertion_id, require_owner
        )
        doc = self._assertion_doc(assertion, badge_class, tenant)
        await self._record_badge_download(tenant_id, assertion, actor_id, actor_role, "json")
        payload = json.dumps(doc, indent=2, ensure_ascii=False).encode("utf-8")
        return RenderedBadge(
            content=payload,
            media_type="application/ld+json",
            filename=f"badge-{assertion_id}.json",
        )

    async def build_badge_png(
        self,
        tenant_id: UUID,
        assertion_id: UUID,
        actor_id: str = "system",
        actor_role: str = "issuer",
        require_owner: str | None = None,
    ) -> RenderedBadge:
        """Build a baked Open Badges PNG for an assertion (U6).

        Fetches the badge class's PNG image and embeds the assertion JSON in its
        ``openbadges`` iTXt chunk. Raises :class:`BadgeImageNotBakeableError`
        when the class has no image or the image is not a PNG (e.g. SVG), which
        the router maps to 422 — the JSON download still works in that case.
        """
        assertion, badge_class, tenant = await self._resolve_for_badge(
            tenant_id, assertion_id, require_owner
        )
        key = badge_class.image_s3_key if badge_class else None
        if not key:
            raise BadgeImageNotBakeableError("this badge has no image to bake")
        if key.lower().endswith(".svg"):
            raise BadgeImageNotBakeableError(
                "badge image is SVG; a PNG image is required to produce a baked badge"
            )
        png_bytes = self._fetch_s3(key)
        if not png_bytes:
            raise BadgeImageNotBakeableError("badge image could not be retrieved")

        doc = self._assertion_doc(assertion, badge_class, tenant)
        baked = bake_png(png_bytes, doc)  # may raise BadgeImageNotBakeableError
        await self._record_badge_download(tenant_id, assertion, actor_id, actor_role, "png")
        return RenderedBadge(
            content=baked,
            media_type="image/png",
            filename=f"badge-{assertion_id}.png",
        )

    async def _resolve_for_badge(
        self, tenant_id: UUID, assertion_id: UUID, require_owner: str | None
    ) -> tuple[BadgeAssertion, BadgeClass | None, Tenant | None]:
        """Resolve assertion (+ownership) + class + tenant for a badge download."""
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_assertion(assertion_id)
        if assertion is None:
            raise CertificateNotFoundError(assertion_id)
        if require_owner is not None and assertion.beneficiary_id != require_owner:
            raise CertificateNotFoundError(assertion_id)
        badge_class = await self._get_class(assertion.badge_class_id)
        tenant = await self._get_tenant(tenant_id)
        return assertion, badge_class, tenant

    def _assertion_doc(
        self,
        assertion: BadgeAssertion,
        badge_class: BadgeClass | None,
        tenant: Tenant | None,
    ) -> dict:
        """Build the OB2.0 Assertion dict from resolved rows (reuses the serializer)."""
        from app.services.issuance_service import new_recipient_salt

        base = f"{self.settings.public_base_url}/api/v1/public/badges"
        issuer = IssuerProfile(
            id_url=f"{base}/issuers/{tenant.id if tenant else assertion.tenant_id}",
            name=(
                (tenant.issuer_name or tenant.name)
                if tenant and (tenant.issuer_name or tenant.name)
                else "Issuer"
            ),
            url=tenant.issuer_url if tenant else None,
            email=tenant.issuer_email if tenant else None,
        )
        bc = BadgeClassData(
            id_url=f"{base}/classes/{assertion.badge_class_id}",
            name=badge_class.name if badge_class else "Badge",
            description=badge_class.description if badge_class else None,
            image_url=None,
            criteria_narrative=badge_class.criteria_narrative if badge_class else None,
            criteria_url=badge_class.criteria_url if badge_class else None,
            issuer=issuer,
            tags=list(badge_class.tags or []) if badge_class else [],
            alignment=list(badge_class.alignment or []) if badge_class else [],
        )
        data = AssertionData(
            id_url=f"{base}/assertions/{assertion.id}",
            recipient_identity=assertion.beneficiary_id,
            recipient_salt=new_recipient_salt(),
            issued_on=assertion.issued_at,
            verify_url=f"{base}/assertions/{assertion.id}",
            badge_class=bc,
            expires=assertion.expires_at,
            revoked=assertion.status == "revoked",
            revocation_reason=assertion.revocation_reason,
        )
        return OpenBadgesSerializer().assertion(data)

    async def _record_badge_download(
        self,
        tenant_id: UUID,
        assertion: BadgeAssertion,
        actor_id: str,
        actor_role: str,
        kind: str,
    ) -> None:
        """Audit + analytics for a badge download, then commit."""
        self._events.record(
            tenant_id=tenant_id,
            event_type="viewed",
            badge_class_id=assertion.badge_class_id,
            assertion_id=assertion.id,
            channel="badge",
        )
        await self._audit.record(
            tenant_id=tenant_id,
            actor_id=actor_id,
            actor_role=actor_role,
            operation="badge:badge_download",
            resource_type="badge_assertion",
            resource_id=str(assertion.id),
            outcome="success",
            metadata={"kind": kind},
        )
        await self.db.commit()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_assertion(self, assertion_id: UUID) -> BadgeAssertion | None:
        result = await self.db.execute(
            select(BadgeAssertion).where(BadgeAssertion.id == assertion_id)
        )
        return result.scalar_one_or_none()

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()

    async def _get_tenant(self, tenant_id: UUID) -> Tenant | None:
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    async def _render_with_custom_template(
        self, template_id: UUID, ctx: CertificateContext
    ) -> tuple[str, bytes]:
        """Render using an issuer-designed template (U5).

        Returns ``(label, pdf)`` where label is ``custom:<id>`` for the audit
        trail. If the template row is missing/archived, falls back to the
        built-in default so the download still succeeds. The custom renderer
        itself falls back to classic on any render error.
        """
        tpl = (
            await self.db.execute(
                select(CertificateTemplate).where(CertificateTemplate.id == template_id)
            )
        ).scalar_one_or_none()
        if tpl is None or tpl.status != "active":
            logger.warning(
                "Custom template %s missing/inactive; using built-in default", template_id
            )
            return (
                self.settings.certificate_default_template,
                render_certificate(ctx, self.settings.certificate_default_template),
            )
        assets = CustomAssets(
            logo=self._fetch_s3(tpl.logo_s3_key) if tpl.logo_s3_key else None,
            background=self._fetch_s3(tpl.background_s3_key) if tpl.background_s3_key else None,
        )
        pdf = render_custom_certificate(ctx, tpl.layout or {}, assets)
        return f"custom:{template_id}", pdf

    def _fetch_s3(self, key: str) -> bytes | None:
        try:
            resp = self._s3.get_object(Bucket=self.settings.s3_bucket_name, Key=key)
            return resp["Body"].read()
        except Exception:
            logger.debug("Could not fetch S3 object %s for certificate", key, exc_info=True)
            return None


def _mask_identity(identity: str) -> str:
    """Render a display name from an identity without exposing a raw email.

    ``alice@example.com`` → ``alice`` (local part), other identifiers pass
    through. Mirrors the "never show raw email" posture used elsewhere.
    """
    if "@" in identity:
        return identity.split("@", 1)[0]
    return identity


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CertificateNotFoundError(Exception):
    def __init__(self, assertion_id: UUID) -> None:
        self.assertion_id = assertion_id
        super().__init__(f"Assertion not found: {assertion_id}")


class CertificateValidationError(Exception):
    pass


class CertificateServiceUnavailableError(Exception):
    pass


async def get_certificate_service(
    db: AsyncSession = Depends(get_db),
) -> CertificateService:
    return CertificateService(db=db, settings=get_settings())
