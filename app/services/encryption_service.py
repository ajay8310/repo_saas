"""
Per-tenant envelope encryption using AWS KMS + AES-256-GCM.

Each document is encrypted with a unique Data Encryption Key (DEK).
The DEK is encrypted with the tenant's Customer Managed Key (CMK) in KMS.

No joins needed — tenant_encryption_keys is queried by tenant_id only.

Requirements: 3.6, 7.3, 13.7
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Result of encrypting document content."""

    ciphertext: bytes
    encrypted_dek: str  # base64-encoded encrypted DEK
    iv: str  # base64-encoded IV/nonce
    tenant_cmk_arn: str


@dataclass(frozen=True, slots=True)
class DecryptedPayload:
    """Result of decrypting document content."""

    plaintext: bytes


class EncryptionService:
    """Envelope encryption: AES-256-GCM with KMS-managed key wrapping.

    Flow:
    1. Generate a 256-bit DEK locally
    2. Encrypt content with AES-256-GCM (unique nonce per document)
    3. Encrypt the DEK using the tenant's CMK via KMS
    4. Return ciphertext + encrypted DEK + nonce
    """

    def __init__(self) -> None:
        settings = get_settings()
        kms_kwargs: dict = {"region_name": settings.aws_region}
        if settings.kms_endpoint_url:
            kms_kwargs["endpoint_url"] = settings.kms_endpoint_url
        if settings.aws_access_key_id:
            kms_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kms_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

        self._kms = boto3.client("kms", **kms_kwargs)

    def encrypt(self, plaintext: bytes, cmk_arn: str) -> EncryptedPayload:
        """Encrypt document content using envelope encryption.

        Args:
            plaintext: Raw document bytes.
            cmk_arn: The tenant's CMK ARN in KMS.

        Returns:
            EncryptedPayload with ciphertext, encrypted DEK, and IV.

        Raises:
            EncryptionUnavailableError: If KMS is unreachable.
        """
        # 1. Generate 256-bit DEK
        dek = os.urandom(32)
        nonce = os.urandom(12)  # 96-bit nonce for GCM

        # 2. Encrypt content with AES-256-GCM
        aesgcm = AESGCM(dek)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)

        # 3. Encrypt DEK with tenant CMK via KMS
        try:
            response = self._kms.encrypt(
                KeyId=cmk_arn,
                Plaintext=dek,
                EncryptionAlgorithm="SYMMETRIC_DEFAULT",
            )
            encrypted_dek = response["CiphertextBlob"]
        except (ClientError, NoCredentialsError) as exc:
            logger.error("KMS encrypt failed for CMK %s: %s", cmk_arn, exc)
            raise EncryptionUnavailableError("KMS service unavailable") from exc
        finally:
            # Wipe plaintext DEK from memory (best effort)
            dek = b"\x00" * 32  # noqa: F841

        return EncryptedPayload(
            ciphertext=ciphertext,
            encrypted_dek=base64.b64encode(encrypted_dek).decode(),
            iv=base64.b64encode(nonce).decode(),
            tenant_cmk_arn=cmk_arn,
        )

    def decrypt(self, encrypted_dek: str, iv: str, ciphertext: bytes) -> DecryptedPayload:
        """Decrypt document content.

        Args:
            encrypted_dek: Base64-encoded encrypted DEK.
            iv: Base64-encoded nonce.
            ciphertext: The encrypted document bytes.

        Returns:
            DecryptedPayload with plaintext bytes.
        """
        # 1. Decrypt DEK via KMS
        try:
            response = self._kms.decrypt(
                CiphertextBlob=base64.b64decode(encrypted_dek),
                EncryptionAlgorithm="SYMMETRIC_DEFAULT",
            )
            dek = response["Plaintext"]
        except (ClientError, NoCredentialsError) as exc:
            logger.error("KMS decrypt failed: %s", exc)
            raise EncryptionUnavailableError("KMS service unavailable") from exc

        # 2. Decrypt content with AES-256-GCM
        nonce = base64.b64decode(iv)
        aesgcm = AESGCM(dek)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)

        return DecryptedPayload(plaintext=plaintext)


class EncryptionUnavailableError(Exception):
    """Raised when KMS is unreachable — never bypass encryption."""
    pass


# ---------------------------------------------------------------------------
# Singleton instance
# ---------------------------------------------------------------------------

_instance: EncryptionService | None = None


def get_encryption_service() -> EncryptionService:
    """Return a cached EncryptionService instance."""
    global _instance
    if _instance is None:
        _instance = EncryptionService()
    return _instance
