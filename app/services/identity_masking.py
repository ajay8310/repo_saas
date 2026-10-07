"""Earner identity masking for public surfaces (Q5=A, BR-P2).

A single place to derive a public display name from an earner identity so no
public view ever leaks a raw email. Used by the directory, public badge, and
certificate paths.

Rules:
* An email ``alice@example.com`` → ``a***e@e***.com`` (first/last of local part,
  first char of domain label, TLD preserved).
* A very short local part (<=2 chars) is masked to its first char + ``*``.
* A non-email identifier is returned unchanged (it is already an opaque handle,
  not personal contact data).
"""

from __future__ import annotations


def mask_identity(identity: str) -> str:
    """Return a privacy-preserving display name for *identity*."""
    if not identity:
        return ""
    if "@" not in identity:
        return identity

    local, _, domain = identity.partition("@")
    masked_local = _mask_part(local)

    # Mask the domain's first label, keep the rest (e.g. example.com).
    if "." in domain:
        first, rest = domain.split(".", 1)
        masked_domain = f"{first[:1]}***.{rest}" if first else f"***.{rest}"
    else:
        masked_domain = f"{domain[:1]}***"

    return f"{masked_local}@{masked_domain}"


def _mask_part(part: str) -> str:
    if len(part) <= 2:
        return f"{part[:1]}*" if part else "*"
    return f"{part[0]}***{part[-1]}"
