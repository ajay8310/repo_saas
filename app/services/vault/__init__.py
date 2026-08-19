"""
Data vault — field-level encryption and blind indexing for personal data.

Public surface::

    from app.services.vault import VaultService, get_vault_service

Providers are selected by the ``vault_provider`` setting.  Adding a managed
vault (HashiCorp Vault, Azure Key Vault, an HSM) means implementing the
``VaultProvider`` protocol in ``providers.py`` and naming it in
``_build_provider`` — no call site changes.
"""

from __future__ import annotations

from app.services.vault.base import (
    SealedValue,
    VaultDecryptError,
    VaultError,
    VaultProvider,
    VaultUnavailableError,
)
from app.services.vault.envelope import looks_sealed, parse, serialise
from app.services.vault.providers import KmsVaultProvider, LocalAesGcmVaultProvider
from app.services.vault.service import VaultService, get_vault_service

__all__ = [
    "KmsVaultProvider",
    "LocalAesGcmVaultProvider",
    "SealedValue",
    "VaultDecryptError",
    "VaultError",
    "VaultProvider",
    "VaultService",
    "VaultUnavailableError",
    "get_vault_service",
    "looks_sealed",
    "parse",
    "serialise",
]
