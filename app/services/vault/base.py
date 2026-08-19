"""
Vault provider contract — the seam external key stores plug into.

A provider does exactly two things: turn plaintext into a self-describing
ciphertext envelope, and turn it back.  Everything policy-shaped (which fields
are sensitive, blind indexing, rotation bookkeeping) lives in VaultService so
that swapping providers cannot change behaviour.

Envelope format (single line, ASCII safe, stored in a text column):

    v1:<provider>:<key_id>:<b64url nonce>:<b64url ciphertext>

The provider tag and key id travel with the value, so a rotation or a provider
migration can decrypt old rows without a schema change or a lookup table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

ENVELOPE_VERSION = "v1"
ENVELOPE_SEPARATOR = ":"
ENVELOPE_PARTS = 5


class VaultError(Exception):
    """Base class for vault failures."""


class VaultUnavailableError(VaultError):
    """The backing key store could not be reached or is misconfigured.

    Raised rather than falling back to plaintext: a vault that silently stops
    encrypting is worse than one that stops working.
    """


class VaultDecryptError(VaultError):
    """The envelope is malformed, or the key that sealed it is unavailable."""


@dataclass(frozen=True, slots=True)
class SealedValue:
    """A parsed ciphertext envelope."""

    version: str
    provider: str
    key_id: str
    nonce: bytes
    ciphertext: bytes


@runtime_checkable
class VaultProvider(Protocol):
    """Encrypts and decrypts individual field values.

    Implementations must be safe to call concurrently.
    """

    name: str

    @property
    def active_key_id(self) -> str:
        """Identifier of the key new values are sealed with."""
        ...

    def seal(self, plaintext: bytes, *, tenant_id: str) -> SealedValue:
        """Encrypt *plaintext*, tagging it with the active key id."""
        ...

    def open_(self, sealed: SealedValue, *, tenant_id: str) -> bytes:
        """Decrypt *sealed*, which may have been produced by an older key."""
        ...
