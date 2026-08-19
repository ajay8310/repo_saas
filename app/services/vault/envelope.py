"""Serialise and parse the vault ciphertext envelope."""

from __future__ import annotations

import base64

from app.services.vault.base import (
    ENVELOPE_PARTS,
    ENVELOPE_SEPARATOR,
    ENVELOPE_VERSION,
    SealedValue,
    VaultDecryptError,
)


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except Exception as exc:  # noqa: BLE001 - normalise to a vault error
        raise VaultDecryptError("Envelope contains invalid base64") from exc


def serialise(sealed: SealedValue) -> str:
    """Render *sealed* as a single-line string safe for a text column."""
    if ENVELOPE_SEPARATOR in sealed.provider or ENVELOPE_SEPARATOR in sealed.key_id:
        raise ValueError("Provider name and key id must not contain ':'")
    return ENVELOPE_SEPARATOR.join(
        (
            sealed.version,
            sealed.provider,
            sealed.key_id,
            _b64e(sealed.nonce),
            _b64e(sealed.ciphertext),
        )
    )


def parse(envelope: str) -> SealedValue:
    """Parse a serialised envelope, raising VaultDecryptError if malformed."""
    if not envelope:
        raise VaultDecryptError("Envelope is empty")

    parts = envelope.split(ENVELOPE_SEPARATOR)
    if len(parts) != ENVELOPE_PARTS:
        raise VaultDecryptError(
            f"Envelope must have {ENVELOPE_PARTS} parts, got {len(parts)}"
        )

    version, provider, key_id, nonce_b64, ct_b64 = parts
    if version != ENVELOPE_VERSION:
        raise VaultDecryptError(f"Unsupported envelope version {version!r}")

    return SealedValue(
        version=version,
        provider=provider,
        key_id=key_id,
        nonce=_b64d(nonce_b64),
        ciphertext=_b64d(ct_b64),
    )


def looks_sealed(value: str | None) -> bool:
    """Return True when *value* appears to be a vault envelope.

    Lets a column hold a mix of sealed and legacy plaintext during a
    backfill, so encryption can be switched on without a stop-the-world
    migration.
    """
    if not value:
        return False
    return value.startswith(ENVELOPE_VERSION + ENVELOPE_SEPARATOR) and (
        value.count(ENVELOPE_SEPARATOR) == ENVELOPE_PARTS - 1
    )
