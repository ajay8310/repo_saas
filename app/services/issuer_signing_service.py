"""Per-tenant issuer signing keys (U4, Q7).

Each tenant (issuer) gets its own RS256 keypair so a certificate is signed by
*that issuer*, not by the platform. The public key is published at the hosted
issuer endpoint, letting any verifier confirm a certificate's signature.

Key storage posture (documented, flagged for ops hardening):

* The **private** key PEM is sealed with :class:`VaultService` when PII
  encryption is enabled (tenant-bound AES-256-GCM), else stored as plaintext
  PEM — the same posture the platform already uses for the JWT keypair.
* The **public** key PEM is stored in the clear (it is meant to be published).

``ensure_keypair`` is idempotent: the first call for a tenant generates and
persists a keypair; later calls return the existing one. Signing and public-key
retrieval both go through it so a tenant that never explicitly provisioned a key
still gets one lazily on first certificate.
"""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)


class IssuerSigningService:
    """Manage and use a tenant's RS256 certificate signing key."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------
    # Key lifecycle
    # ------------------------------------------------------------------

    async def ensure_keypair(self, tenant_id: UUID) -> tuple[str, str]:
        """Return ``(key_id, public_pem)``, generating the keypair if absent.

        Idempotent. ``tenants`` is the root entity (not RLS-scoped), so this
        reads/writes it directly without a tenant GUC.
        """
        tenant = await self._get_tenant(tenant_id)
        if tenant is None:
            raise IssuerKeyError(f"tenant not found: {tenant_id}")

        if tenant.issuer_signing_public_key and tenant.issuer_key_id:
            return tenant.issuer_key_id, tenant.issuer_signing_public_key

        private_pem, public_pem = _generate_rsa_pem()
        key_id = f"isk_{secrets.token_hex(8)}"

        tenant.issuer_signing_public_key = public_pem
        tenant.issuer_signing_private_key = self._seal_private(private_pem, tenant_id)
        tenant.issuer_key_id = key_id
        tenant.issuer_key_generated_at = datetime.now(UTC)
        await self.db.commit()
        logger.info("Generated issuer signing keypair %s for tenant %s", key_id, tenant_id)
        return key_id, public_pem

    async def public_pem(self, tenant_id: UUID) -> str:
        """Return the issuer's public key PEM (generating the keypair if absent)."""
        _, public_pem = await self.ensure_keypair(tenant_id)
        return public_pem

    async def public_jwk_reference(self, tenant_id: UUID) -> dict:
        """A small descriptor published alongside the hosted issuer profile."""
        key_id, public_pem = await self.ensure_keypair(tenant_id)
        return {
            "kid": key_id,
            "alg": "RS256",
            "use": "sig",
            "publicKeyPem": public_pem,
        }

    # ------------------------------------------------------------------
    # Signing
    # ------------------------------------------------------------------

    async def sign(self, tenant_id: UUID, payload: dict) -> str:
        """Sign *payload* with the tenant's issuer key, returning a compact JWS."""
        from jose import jwt

        tenant = await self._get_tenant(tenant_id)
        if tenant is None:
            raise IssuerKeyError(f"tenant not found: {tenant_id}")
        if not tenant.issuer_signing_private_key or not tenant.issuer_key_id:
            await self.ensure_keypair(tenant_id)
            tenant = await self._get_tenant(tenant_id)

        private_pem = self._open_private(tenant.issuer_signing_private_key, tenant_id)
        headers = {"kid": tenant.issuer_key_id}
        return jwt.encode(payload, private_pem, algorithm="RS256", headers=headers)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_tenant(self, tenant_id: UUID) -> Tenant | None:
        # tenants is not RLS-scoped; still set context so any downstream query
        # in the same session behaves. Harmless for the root table.
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(select(Tenant).where(Tenant.id == tenant_id))
        return result.scalar_one_or_none()

    def _seal_private(self, private_pem: str, tenant_id: UUID) -> str:
        """Seal the private key when PII encryption is on, else store plaintext."""
        if not self.settings.pii_encryption_enabled:
            return private_pem
        from app.services.vault.service import get_vault_service

        sealed = get_vault_service().seal(private_pem, tenant_id=str(tenant_id))
        return sealed or private_pem

    def _open_private(self, stored: str, tenant_id: UUID) -> str:
        """Open a sealed private key; pass through plaintext PEM unchanged."""
        if not self.settings.pii_encryption_enabled:
            return stored
        from app.services.vault.service import get_vault_service

        opened = get_vault_service().open_text(stored, tenant_id=str(tenant_id))
        return opened or stored


def _generate_rsa_pem() -> tuple[str, str]:
    """Generate a 2048-bit RSA keypair, returning ``(private_pem, public_pem)``."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private_pem, public_pem


class IssuerKeyError(Exception):
    pass


async def get_issuer_signing_service(
    db: AsyncSession = Depends(get_db),
) -> IssuerSigningService:
    return IssuerSigningService(db=db, settings=get_settings())
