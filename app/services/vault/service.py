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
