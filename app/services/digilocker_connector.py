"""
DigiLocker issuer connector — publishes issued credentials to a citizen's locker.

Previously this posted to a hardcoded ``.../placeholder`` URL with no
authentication, and ``attempt_push`` had no caller anywhere in the codebase, so
push rows accumulated in ``pending`` forever. This module now does the real
thing: OAuth 2.0 client-credentials against the configured token endpoint, a
cached access token, and a document-issue call carrying the doctype and
beneficiary reference DigiLocker needs.

Two modes, because the workflow has to be usable before an authority's
Meripehchaan credentials arrive:

``sandbox`` (default)
    Records a synthetic ``digilocker_uri`` and marks the push successful without
    any network call. The push row is explicitly tagged ``sandbox`` so nobody
    can mistake it for a real publication.

``live``
    Calls DigiLocker. Startup validation refuses to run in this mode without
    every required credential, so a misconfiguration surfaces as a boot failure
    rather than as an endless retry loop.

Retry state lives in ``digilocker_pushes.attempt_count`` rather than in the
Celery task, so a broker restart cannot lose an authority's audit trail of
publication attempts.

Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6
"""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
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
from app.models.document import Document

logger = logging.getLogger(__name__)

# Statuses that mean "no further attempt should be made".
TERMINAL_STATUSES = frozenset({"success", "permanently_failed"})

# Access tokens are cached per client id. Module-level rather than per-request
# because a connector instance lives for one request and re-authenticating on
# every push would be both slow and rude to DigiLocker's token endpoint.
_token_cache: dict[str, tuple[str, float]] = {}

# Refresh slightly early so a token cannot expire mid-flight.
_TOKEN_EXPIRY_SKEW_SECONDS = 30


class DigiLockerError(Exception):
    """A DigiLocker publication could not be completed."""


class DigiLockerConfigError(DigiLockerError):
    """Live mode is selected but the connector is not usable."""


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Outcome of a publication attempt."""

    push_id: UUID
    status: str
    digilocker_uri: str | None
    attempt_count: int
    failure_reason: str | None
    sandbox: bool


class DigiLockerConnector:
    """Publishes issued credentials to DigiLocker."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    @property
    def is_sandbox(self) -> bool:
        return self.settings.digilocker_mode != "live"

    # ------------------------------------------------------------------
    # Push records
    # ------------------------------------------------------------------

    async def enqueue_push(
        self,
        tenant_id: UUID,
        document_id: UUID,
        doctype: str | None = None,
    ) -> DigiLockerPush:
        """Create or reuse a push record for *document_id*.

        Reuses an existing non-terminal row so that publishing the same
        credential twice does not create a second pending push competing with
        the first. A credential already published successfully returns that row
        unchanged rather than being sent again.
        """
        await set_tenant_context(self.db, str(tenant_id))

        existing = (
            await self.db.execute(
                select(DigiLockerPush)
                .where(DigiLockerPush.document_id == document_id)
                .order_by(DigiLockerPush.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing is not None and existing.status != "permanently_failed":
            if doctype and not existing.doctype:
                existing.doctype = doctype
                await self.db.commit()
            return existing

        push = DigiLockerPush(
            tenant_id=tenant_id,
            document_id=document_id,
            status="pending",
            doctype=doctype or self.settings.digilocker_default_doctype,
        )
        self.db.add(push)
        await self.db.commit()
        await self.db.refresh(push)
        return push

    async def get_push_for_document(
        self, tenant_id: UUID, document_id: UUID
    ) -> DigiLockerPush | None:
        """Return the latest push record for a credential, if any."""
        await set_tenant_context(self.db, str(tenant_id))
        return (
            await self.db.execute(
                select(DigiLockerPush)
                .where(DigiLockerPush.document_id == document_id)
                .order_by(DigiLockerPush.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def list_pushes(
        self,
        tenant_id: UUID,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DigiLockerPush]:
        """List push records for a tenant, newest first."""
        await set_tenant_context(self.db, str(tenant_id))
        stmt = (
            select(DigiLockerPush)
            .order_by(DigiLockerPush.created_at.desc())
            .limit(max(1, min(limit, 500)))
            .offset(max(0, offset))
        )
        if status:
            stmt = stmt.where(DigiLockerPush.status == status)
        return list((await self.db.execute(stmt)).scalars().all())


    # ------------------------------------------------------------------
    # Publication
    # ------------------------------------------------------------------

    async def publish(
        self,
        tenant_id: UUID,
        document_id: UUID,
        doctype: str | None = None,
    ) -> PublishResult:
        """Publish a credential to DigiLocker now, synchronously.

        Used by the issuer-facing endpoint so an officer gets an immediate
        answer. The background sweep uses ``attempt_push`` for the same work.
        """
        push = await self.enqueue_push(tenant_id, document_id, doctype)

        if push.status == "success":
            # Idempotent: already in the citizen's locker.
            return PublishResult(
                push_id=push.id,
                status=push.status,
                digilocker_uri=push.digilocker_uri,
                attempt_count=push.attempt_count,
                failure_reason=None,
                sandbox=push.delivery_mode == "sandbox",
            )

        await self.attempt_push(push.id, tenant_id=tenant_id)
        await self.db.refresh(push)

        return PublishResult(
            push_id=push.id,
            status=push.status,
            digilocker_uri=push.digilocker_uri,
            attempt_count=push.attempt_count,
            failure_reason=push.failure_reason,
            sandbox=push.delivery_mode == "sandbox",
        )

    async def attempt_push(
        self, push_id: UUID, tenant_id: UUID | None = None
    ) -> bool:
        """Attempt one publication.

        On failure increments ``attempt_count`` and marks the row ``retrying``
        until ``digilocker_max_retries`` is reached, then ``permanently_failed``.

        *tenant_id* should always be supplied: ``digilocker_pushes`` is
        RLS-protected, so without a tenant context the lookup matches no rows.
        """
        if tenant_id is not None:
            await set_tenant_context(self.db, str(tenant_id))

        push = (
            await self.db.execute(
                select(DigiLockerPush).where(DigiLockerPush.id == push_id)
            )
        ).scalar_one_or_none()

        if push is None:
            logger.warning("DigiLocker push %s not found", push_id)
            return False

        if push.status in TERMINAL_STATUSES:
            return push.status == "success"

        push.attempt_count += 1
        push.last_attempt_at = datetime.now(timezone.utc)

        document = (
            await self.db.execute(
                select(Document).where(Document.id == push.document_id)
            )
        ).scalar_one_or_none()

        if document is None:
            # The credential is gone; retrying cannot help.
            push.status = "permanently_failed"
            push.failure_reason = "Source document no longer exists"
            await self.db.commit()
            return False

        try:
            uri = await self._deliver(push, document)
        except DigiLockerError as exc:
            push.failure_reason = str(exc)
            self._mark_retry_or_fail(push)
            await self.db.commit()
            logger.warning(
                "DigiLocker push %s failed (attempt %d/%d): %s",
                push_id,
                push.attempt_count,
                self.settings.digilocker_max_retries,
                exc,
            )
            return False

        push.status = "success"
        push.digilocker_uri = uri
        push.published_at = datetime.now(timezone.utc)
        push.failure_reason = None
        push.delivery_mode = "sandbox" if self.is_sandbox else "live"
        await self.db.commit()

        logger.info(
            "DigiLocker publication succeeded: doc=%s uri=%s mode=%s",
            push.document_id, uri, push.delivery_mode,
        )
        return True

    def _mark_retry_or_fail(self, push: DigiLockerPush) -> None:
        """Decide whether a failed push is retryable."""
        if push.attempt_count >= self.settings.digilocker_max_retries:
            push.status = "permanently_failed"
            logger.error(
                "DigiLocker push permanently failed after %d attempts: doc=%s",
                push.attempt_count, push.document_id,
            )
        else:
            push.status = "retrying"


    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    async def _deliver(self, push: DigiLockerPush, document: Document) -> str:
        """Deliver the credential and return its DigiLocker URI."""
        if self.is_sandbox:
            return self._sandbox_uri(push, document)

        token = await self._access_token()
        doctype = push.doctype or self.settings.digilocker_default_doctype

        # DigiLocker identifies a document by issuer + doctype + a URI the
        # issuer controls. The credential id is used directly so the mapping
        # back from a locker entry to our record is unambiguous.
        payload = {
            "orgId": self.settings.digilocker_issuer_id,
            "docType": doctype,
            "docId": str(document.id),
            # Hashed, not raw: the beneficiary identifier is personal data and
            # this is a cross-organisation call.
            "beneficiaryRef": hashlib.sha256(
                f"{document.tenant_id}|{document.beneficiary_id}".encode()
            ).hexdigest(),
            "issuedOn": document.created_at.isoformat() if document.created_at else None,
            "schemaVersion": document.schema_version,
        }

        url = f"{self.settings.digilocker_base_url.rstrip('/')}/issue"

        try:
            async with httpx.AsyncClient(
                timeout=float(self.settings.digilocker_push_timeout_seconds)
            ) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.HTTPError as exc:
            raise DigiLockerError(f"DigiLocker unreachable: {exc}") from exc

        if response.status_code in (401, 403):
            # Drop the cached token so the next attempt re-authenticates rather
            # than replaying a token DigiLocker has already rejected.
            _token_cache.pop(self._token_cache_key(), None)
            raise DigiLockerError(
                f"DigiLocker rejected our credentials (HTTP {response.status_code})"
            )

        if not 200 <= response.status_code < 300:
            raise DigiLockerError(
                f"DigiLocker returned HTTP {response.status_code}: "
                f"{response.text[:200]}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DigiLockerError("DigiLocker returned a non-JSON response") from exc

        uri = body.get("uri") or body.get("docUri")
        if not uri:
            raise DigiLockerError(
                "DigiLocker accepted the document but returned no URI; "
                "treating as failed so it is retried rather than recorded as "
                "published without a locker reference"
            )
        return str(uri)

    def _sandbox_uri(self, push: DigiLockerPush, document: Document) -> str:
        """Build a deterministic fake URI for sandbox mode."""
        issuer = self.settings.digilocker_issuer_id or "SANDBOX"
        doctype = push.doctype or self.settings.digilocker_default_doctype
        return f"in.gov.sandbox-{issuer}-{doctype}-{document.id}"

    def _token_cache_key(self) -> str:
        return f"{self.settings.digilocker_token_url}|{self.settings.digilocker_client_id}"

    async def _access_token(self) -> str:
        """Return a cached or freshly minted OAuth 2.0 access token."""
        key = self._token_cache_key()
        cached = _token_cache.get(key)
        if cached is not None:
            token, expires_at = cached
            if time.monotonic() < expires_at:
                return token

        data = {
            "grant_type": "client_credentials",
            "client_id": self.settings.digilocker_client_id,
            "client_secret": self.settings.digilocker_client_secret,
        }

        try:
            async with httpx.AsyncClient(
                timeout=float(self.settings.digilocker_push_timeout_seconds)
            ) as client:
                response = await client.post(
                    self.settings.digilocker_token_url,
                    data=data,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.HTTPError as exc:
            raise DigiLockerError(f"DigiLocker token endpoint unreachable: {exc}") from exc

        if not 200 <= response.status_code < 300:
            raise DigiLockerError(
                f"DigiLocker token request failed with HTTP {response.status_code}"
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise DigiLockerError("Token endpoint returned a non-JSON response") from exc

        token = body.get("access_token")
        if not token:
            raise DigiLockerError("Token endpoint returned no access_token")

        # Default to a conservative lifetime when the server omits expires_in.
        lifetime = int(body.get("expires_in") or 300)
        _token_cache[key] = (
            str(token),
            time.monotonic() + max(1, lifetime - _TOKEN_EXPIRY_SKEW_SECONDS),
        )
        return str(token)


async def get_digilocker_connector(
    db: AsyncSession = Depends(get_db),
) -> DigiLockerConnector:
    """Provide a DigiLockerConnector for route handlers."""
    return DigiLockerConnector(db=db, settings=get_settings())
