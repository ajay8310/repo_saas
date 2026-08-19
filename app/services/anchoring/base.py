"""
Anchor provider contract — the seam a ledger plugs into.

An anchor provider publishes one Merkle root and returns a reference that a
third party can independently resolve.  That is the whole contract: everything
about batching, proof generation, and storage lives in ``AnchoringService`` so
that changing ledgers cannot change what a credential's proof means.

Why this shape:

- Batching happens above the provider, so a chain that charges per transaction
  and a local transparency log cost the same number of calls.
- ``ledger_ref`` is opaque.  For an EVM chain it is a transaction hash; for the
  local ledger it is a sequence number.  Verification never interprets it.
- Providers publish, they do not verify.  Inclusion is proved by recomputing the
  Merkle root, which needs no ledger access at all.  The ledger only establishes
  *when* the root existed and that it has not changed since.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


class AnchorError(Exception):
    """Base class for anchoring failures."""


class AnchorUnavailableError(AnchorError):
    """The ledger could not be reached or is misconfigured.

    Anchoring is asynchronous and retried, so this is never fatal to issuance.
    """


@dataclass(frozen=True, slots=True)
class AnchorReceipt:
    """Proof that a root was published to a ledger."""

    provider: str
    ledger_ref: str
    root_hex: str
    anchored_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class AnchorProvider(Protocol):
    """Publishes Merkle roots to an external ledger."""

    name: str

    async def publish(self, root_hex: str, *, batch_id: str) -> AnchorReceipt:
        """Publish *root_hex*, returning a resolvable reference.

        Must raise ``AnchorUnavailableError`` rather than returning a partial
        receipt: a recorded anchor that was never actually published would make
        the audit trail lie.
        """
        ...

    async def resolve(self, ledger_ref: str) -> str | None:
        """Return the root recorded at *ledger_ref*, or None if absent.

        Lets the platform detect a root that was reorganised away or tampered
        with after publication.
        """
        ...
