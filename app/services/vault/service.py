"""
VaultService — field-level protection for personal data.

Two capabilities, deliberately separated:

``seal``/``open_text``
    Confidentiality.  AES-256-GCM with the tenant id bound as additional
    authenticated data, so a ciphertext cannot be replayed into another
    tenant's row.

``blind_index``
    Searchability.  A keyed HMAC-SHA256 over the normalised value.  Equality
    lookups and uniqueness constraints keep working against the index column
    while the real value stays encrypted.  This is *not* a substitute for
    encryption: it is deterministic by design, so it leaks equality (two rows
    with the same email share an index) and nothing more.

Why a blind index at all: ``documents.beneficiary_id`` is both personal data
and the primary lookup key for "my documents".  Encrypting it without an index
would force a full-table decrypt per query.

DPDP note: this supports the security-safeguards obligation and makes erasure
cheap — dropping a tenant key generation renders every sealed value for that
tenant unrecoverable (crypto-shredding), which is more reliable than chasing
rows across partitions and backups.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings, get_settings
from app.services.vault.base import (
    VaultDecryptError,
    VaultProvider,
    VaultUnavailableError,
)
from app.services.vault.envelope import looks_sealed, parse, serialise
from app.services.vault.providers import KmsVaultProvider, LocalAesGcmVaultProvider

logger = logging.getLogger(__name__)

_BLIND_INDEX_BYTES = 32


def _bootstrap_key(settings: Settings, purpose: str) -> bytes:
    """Derive a vault key from the JWT private key when none is configured.

    Sealing is not optional — webhook signing secrets must be recoverable, so a
    deployment that has not provisioned ``vault_root_key`` still needs a usable
    key rather than a hard failure on first use.

    HKDF with a purpose-specific info label keeps the derived key
    cryptographically independent of the JWT signing usage, and of the other
    vault purpose.  This is a bootstrap convenience, not a recommendation: an
    explicit ``vault_root_key`` can be rotated independently of the JWT keypair,
    and rotating the JWT keypair here would silently orphan every sealed value.
    """
    logger.warning(
        "Vault key for %r is not configured; deriving one from jwt_private_key. "
        "Set vault_root_key and vault_blind_index_key explicitly — rotating the "
        "JWT keypair would otherwise make existing sealed values unreadable.",
        purpose,
    )
    ikm = settings.jwt_private_key.encode()
    if not ikm:
        raise VaultUnavailableError(
            "Cannot derive a vault key: neither vault keys nor jwt_private_key are set"
        )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=f"repo_saas/vault/bootstrap/{purpose}".encode(),
    ).derive(ikm)


def _decode_key(raw: str, *, field: str) -> bytes:
    """Decode a base64 or hex key from configuration."""
    if not raw:
        raise VaultUnavailableError(f"{field} is not configured")
    try:
        if len(raw) == 64 and all(c in "0123456789abcdefABCDEF" for c in raw):
            return bytes.fromhex(raw)
        padding = "=" * (-len(raw) % 4)
        return base64.b64decode(raw + padding)
    except Exception as exc:  # noqa: BLE001
        raise VaultUnavailableError(f"{field} is not valid base64 or hex") from exc


def _build_provider(settings: Settings) -> VaultProvider:
    """Select the provider named in configuration."""
    provider = settings.vault_provider
    if provider == "kms":
        return KmsVaultProvider(
            key_arn=settings.vault_kms_key_arn,
            region=settings.aws_region,
            endpoint_url=settings.kms_endpoint_url or None,
        )
    if provider == "local":
        root = (
            _decode_key(settings.vault_root_key, field="vault_root_key")
            if settings.vault_root_key
            else _bootstrap_key(settings, "root")
        )
        return LocalAesGcmVaultProvider(
            root_key=root,
            key_id=settings.vault_active_key_id,
        )
    raise VaultUnavailableError(f"Unknown vault provider {provider!r}")


class VaultService:
    """Seals and opens personal-data field values."""

    def __init__(self, provider: VaultProvider, blind_index_key: bytes) -> None:
        self._provider = provider
        self._blind_index_key = blind_index_key

    @property
    def provider_name(self) -> str:
        return self._provider.name

    # ------------------------------------------------------------------
    # Confidentiality
    # ------------------------------------------------------------------

    def seal(self, plaintext: str | None, *, tenant_id: str) -> str | None:
        """Encrypt *plaintext*, returning a storable envelope string.

        ``None`` and ``""`` pass through unchanged: a missing value carries no
        information worth protecting, and preserving the distinction keeps
        "cleared" semantics working for nullable columns.
        """
        if plaintext is None or plaintext == "":
            return plaintext
        sealed = self._provider.seal(plaintext.encode("utf-8"), tenant_id=tenant_id)
        return serialise(sealed)

    def open_text(self, envelope: str | None, *, tenant_id: str) -> str | None:
        """Decrypt an envelope produced by :meth:`seal`.

        Values that are not envelopes are returned unchanged, so a column can
        be backfilled incrementally rather than in one migration.
        """
        if envelope is None or envelope == "":
            return envelope
        if not looks_sealed(envelope):
            return envelope
        plaintext = self._provider.open_(parse(envelope), tenant_id=tenant_id)
        return plaintext.decode("utf-8")

    def try_open_text(self, envelope: str | None, *, tenant_id: str) -> str | None:
        """Like :meth:`open_text` but returns None instead of raising.

        For read paths that must degrade rather than fail — rendering a list
        where one unreadable row should not 500 the whole page.  Crypto-shredded
        values land here after erasure.
        """
        try:
            return self.open_text(envelope, tenant_id=tenant_id)
        except (VaultDecryptError, VaultUnavailableError):
            logger.warning("Vault could not open a value for tenant %s", tenant_id)
            return None

    # ------------------------------------------------------------------
    # Searchability
    # ------------------------------------------------------------------

    def blind_index(self, value: str | None, *, tenant_id: str) -> str | None:
        """Return a deterministic, keyed index for *value*.

        Normalisation (NFKC, strip, casefold) means ``"A@B.com "`` and
        ``"a@b.com"`` share an index, which is what callers expect for emails
        and identifiers.  The tenant id is mixed into the MAC so the same email
        in two tenants produces different indexes — otherwise the index itself
        would leak cross-tenant membership.
        """
        if value is None or value == "":
            return None
        normalised = unicodedata.normalize("NFKC", value).strip().casefold()
        mac = hmac.new(
            self._blind_index_key,
            f"{tenant_id}\x00{normalised}".encode(),
            hashlib.sha256,
        )
        return mac.hexdigest()[: _BLIND_INDEX_BYTES * 2]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_vault_service() -> VaultService:
    """Build a VaultService from settings.

    Deliberately uncached: settings are reloadable in tests, and provider
    construction is cheap (the KMS provider builds its boto3 client per call).
    """
    settings = get_settings()
    blind_key = (
        _decode_key(settings.vault_blind_index_key, field="vault_blind_index_key")
        if settings.vault_blind_index_key
        else _bootstrap_key(settings, "blind-index")
    )
    return VaultService(
        provider=_build_provider(settings),
        blind_index_key=blind_key,
    )
