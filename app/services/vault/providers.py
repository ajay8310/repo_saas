"""
Concrete vault providers.

``LocalAesGcmVaultProvider`` keeps key material in application config and is
appropriate for development, on-premise installs, and any deployment where a
managed KMS is not available.  ``KmsVaultProvider`` performs envelope
encryption against AWS KMS so plaintext data keys never persist.

Both derive a per-tenant key from the configured root key, so a bug that
mislays a tenant id cannot decrypt another tenant's values.
"""

from __future__ import annotations

import logging
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.services.vault.base import (
    SealedValue,
    VaultDecryptError,
    VaultUnavailableError,
)

logger = logging.getLogger(__name__)

_NONCE_BYTES = 12  # AES-GCM standard nonce length
_KEY_BYTES = 32  # AES-256


def _derive_tenant_key(root: bytes, tenant_id: str, key_id: str) -> bytes:
    """Derive a per-tenant, per-key-generation AES key via HKDF-SHA256.

    Including *key_id* in the info string means rotating the root key produces
    a different derived key while old envelopes remain decryptable, because the
    envelope records the key id it was sealed with.
    """
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=None,
        info=f"repo_saas/vault/{key_id}/{tenant_id}".encode(),
    ).derive(root)


class LocalAesGcmVaultProvider:
    """AES-256-GCM using a root key held in configuration.

    The root key is never used directly; each tenant gets an HKDF-derived
    subkey.  Suitable wherever the config store itself is the trust boundary
    (sealed secrets, Vault agent sidecar, environment injected by the platform).
    """

    name = "local"

    def __init__(self, root_key: bytes, key_id: str = "k1") -> None:
        if len(root_key) < _KEY_BYTES:
            raise VaultUnavailableError(
                f"Vault root key must be at least {_KEY_BYTES} bytes, "
                f"got {len(root_key)}"
            )
        self._root = root_key
        self._key_id = key_id

    @property
    def active_key_id(self) -> str:
        return self._key_id

    def seal(self, plaintext: bytes, *, tenant_id: str) -> SealedValue:
        key = _derive_tenant_key(self._root, tenant_id, self._key_id)
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, tenant_id.encode())
        return SealedValue(
            version="v1",
            provider=self.name,
            key_id=self._key_id,
            nonce=nonce,
            ciphertext=ciphertext,
        )

    def open_(self, sealed: SealedValue, *, tenant_id: str) -> bytes:
        key = _derive_tenant_key(self._root, tenant_id, sealed.key_id)
        try:
            # tenant_id is bound as AAD, so a value cannot be moved between
            # tenants even by someone who can write to the column.
            return AESGCM(key).decrypt(sealed.nonce, sealed.ciphertext, tenant_id.encode())
        except Exception as exc:  # noqa: BLE001 - all failures are the same to callers
            raise VaultDecryptError(
                "Vault could not decrypt the value (wrong key, wrong tenant, "
                "or tampered ciphertext)"
            ) from exc


class KmsVaultProvider:
    """Envelope encryption against AWS KMS.

    Each value gets a fresh data key from ``GenerateDataKey``; the wrapped key
    travels inside the ciphertext so no separate DEK column is needed.  The
    plaintext data key is used once and dropped.
    """

    name = "kms"

    def __init__(self, key_arn: str, region: str, endpoint_url: str | None = None) -> None:
        if not key_arn:
            raise VaultUnavailableError("KMS vault provider requires a key ARN")
        self._key_arn = key_arn
        self._region = region
        self._endpoint_url = endpoint_url

    @property
    def active_key_id(self) -> str:
        # The alias/last path segment is enough to identify the CMK; the full
        # ARN would bloat every stored value.
        return self._key_arn.rsplit("/", 1)[-1]

    def _client(self):  # noqa: ANN202 - boto3 client is untyped
        import boto3

        return boto3.client(
            "kms", region_name=self._region, endpoint_url=self._endpoint_url
        )

    def seal(self, plaintext: bytes, *, tenant_id: str) -> SealedValue:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            response = self._client().generate_data_key(
                KeyId=self._key_arn,
                KeySpec="AES_256",
                EncryptionContext={"tenant_id": tenant_id},
            )
            dek = response["Plaintext"]
            wrapped = response["CiphertextBlob"]
        except (ClientError, BotoCoreError, KeyError) as exc:
            raise VaultUnavailableError(f"KMS GenerateDataKey failed: {exc}") from exc

        try:
            nonce = os.urandom(_NONCE_BYTES)
            body = AESGCM(dek).encrypt(nonce, plaintext, tenant_id.encode())
        finally:
            del dek

        # Prefix the wrapped key so open_ can recover it without a side table.
        payload = len(wrapped).to_bytes(4, "big") + wrapped + body
        return SealedValue(
            version="v1",
            provider=self.name,
            key_id=self.active_key_id,
            nonce=nonce,
            ciphertext=payload,
        )

    def open_(self, sealed: SealedValue, *, tenant_id: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        blob = sealed.ciphertext
        if len(blob) < 4:
            raise VaultDecryptError("KMS envelope is truncated")
        wrapped_len = int.from_bytes(blob[:4], "big")
        wrapped, body = blob[4 : 4 + wrapped_len], blob[4 + wrapped_len :]
        if len(wrapped) != wrapped_len:
            raise VaultDecryptError("KMS envelope is truncated")

        try:
            dek = self._client().decrypt(
                CiphertextBlob=wrapped,
                EncryptionContext={"tenant_id": tenant_id},
            )["Plaintext"]
        except (ClientError, BotoCoreError, KeyError) as exc:
            raise VaultUnavailableError(f"KMS Decrypt failed: {exc}") from exc

        try:
            return AESGCM(dek).decrypt(sealed.nonce, body, tenant_id.encode())
        except Exception as exc:  # noqa: BLE001
            raise VaultDecryptError("Vault could not decrypt the value") from exc
        finally:
            del dek
