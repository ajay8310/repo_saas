"""
Ledger anchoring — tamper-evident proof that a credential existed.

Public surface::

    from app.services.anchoring import AnchoringService, get_anchoring_service

Adding a ledger means implementing ``AnchorProvider`` in ``providers.py`` and
naming it in ``build_provider``. Call sites do not change.
"""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_db
from app.services.anchoring.base import (
    AnchorError,
    AnchorProvider,
    AnchorReceipt,
    AnchorUnavailableError,
)
from app.services.anchoring.merkle import (
    InclusionProof,
    MerkleTree,
    leaf_hash,
    node_hash,
    verify_inclusion,
    verify_inclusion_from_leaf,
)
from app.services.anchoring.providers import (
    EvmAnchorProvider,
    FabricAnchorProvider,
    LocalLedgerAnchorProvider,
)
from app.services.anchoring.service import (
    AnchoringService,
    beneficiary_ref,
    build_provider,
    canonical_leaf,
)

__all__ = [
    "AnchorError",
    "AnchorProvider",
    "AnchorReceipt",
    "AnchorUnavailableError",
    "AnchoringService",
    "EvmAnchorProvider",
    "FabricAnchorProvider",
    "InclusionProof",
    "LocalLedgerAnchorProvider",
    "MerkleTree",
    "beneficiary_ref",
    "build_provider",
    "canonical_leaf",
    "get_anchoring_service",
    "leaf_hash",
    "node_hash",
    "verify_inclusion",
    "verify_inclusion_from_leaf",
]


async def get_anchoring_service(
    db: AsyncSession = Depends(get_db),
) -> AnchoringService:
    """Provide an AnchoringService for route handlers."""
    return AnchoringService(db=db, settings=get_settings())
