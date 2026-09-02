"""
AnchoringService — batches credential digests, publishes roots, serves proofs.

The digest committed for a document is deliberately *not* the encrypted blob.
It is a canonical JSON summary of the credential's identity and integrity
metadata:

    {credential_id, tenant_id, schema_id, schema_version,
     beneficiary_ref, content_sha256, issued_at}

Two reasons.  Anchoring ciphertext would tie the proof to a particular
encryption, so re-encrypting during key rotation would invalidate every
historical proof.  And ``beneficiary_ref`` is a salted hash, never the raw
identifier, because anything committed to a public ledger is permanent and
unredactable — putting a beneficiary identifier on-chain would directly conflict
with the DPDP erasure obligation.

Verification therefore proves: this credential, with this content, was issued by
this tenant under this schema, and existed no later than the anchor timestamp.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.middleware.tenant_context import set_tenant_context
from app.models.anchor import AnchorBatch, DocumentAnchor
from app.models.document import Document
from app.services.anchoring.base import AnchorProvider, AnchorUnavailableError
from app.services.anchoring.merkle import (
    InclusionProof,
    MerkleTree,
    leaf_hash,
    verify_inclusion_from_leaf,
)
from app.services.anchoring.providers import (
    EvmAnchorProvider,
    FabricAnchorProvider,
    LocalLedgerAnchorProvider,
)

logger = logging.getLogger(__name__)


def canonical_leaf(
    *,
    credential_id: str,
    tenant_id: str,
    schema_id: str,
    schema_version: int,
    beneficiary_ref: str,
    content_sha256: str,
    issued_at: str,
) -> bytes:
    """Serialise a credential commitment deterministically.

    ``sort_keys`` plus fixed separators means the same credential always yields
    the same bytes regardless of dict ordering or Python version, which is
    essential: a proof recomputed years later must hash identically.
    """
    return json.dumps(
        {
            "credential_id": credential_id,
            "tenant_id": tenant_id,
            "schema_id": schema_id,
            "schema_version": schema_version,
            "beneficiary_ref": beneficiary_ref,
            "content_sha256": content_sha256,
            "issued_at": issued_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def beneficiary_ref(beneficiary_id: str, tenant_id: str) -> str:
    """Salted, tenant-scoped hash standing in for the raw beneficiary id.

    Never put a beneficiary identifier on a ledger: anchors are immutable, so
    such a record could not be erased on request.
    """
    return hashlib.sha256(
        f"anchor-ref|{tenant_id}|{beneficiary_id}".encode()
    ).hexdigest()


def build_provider(settings: Settings, db: AsyncSession) -> AnchorProvider:
    """Select the anchor provider named in configuration."""
    name = settings.anchor_provider
    if name == "local":
        return LocalLedgerAnchorProvider(db=db)
    if name == "evm":
        return EvmAnchorProvider(
            rpc_url=settings.anchor_rpc_url,
            signer_url=settings.anchor_signer_url,
            contract_address=settings.anchor_contract_address,
        )
    if name == "fabric":
        return FabricAnchorProvider()
    raise AnchorUnavailableError(f"Unknown anchor provider {name!r}")


class AnchoringService:
    """Records credential commitments and publishes them in batches."""

    def __init__(
        self,
        db: AsyncSession,
        settings: Settings,
        provider: AnchorProvider | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self._provider = provider or build_provider(settings, db)

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    async def record_document(
        self,
        *,
        tenant_id: UUID,
        document: Document,
        content_sha256: str,
    ) -> DocumentAnchor:
        """Commit *document* to the next batch.

        Called on issuance.  The leaf is computed and stored immediately so the
        commitment is fixed at issuance time rather than at batch time —
        otherwise a later edit could change what gets anchored.
        """
        await set_tenant_context(self.db, str(tenant_id))

        payload = canonical_leaf(
            credential_id=str(document.id),
            tenant_id=str(tenant_id),
            schema_id=str(document.schema_id),
            schema_version=document.schema_version,
            beneficiary_ref=beneficiary_ref(document.beneficiary_id, str(tenant_id)),
            content_sha256=content_sha256,
            issued_at=(
                document.created_at.isoformat()
                if document.created_at
                else datetime.now(UTC).isoformat()
            ),
        )

        anchor = DocumentAnchor(
            tenant_id=tenant_id,
            document_id=document.id,
            leaf_hex=leaf_hash(payload).hex(),
        )
        self.db.add(anchor)
        await self.db.commit()
        await self.db.refresh(anchor)
        return anchor

    # ------------------------------------------------------------------
    # Batching and publication
    # ------------------------------------------------------------------

    async def anchor_pending(
        self, tenant_id: UUID, *, max_leaves: int = 4096
    ) -> AnchorBatch | None:
        """Build a Merkle tree over unanchored commitments and publish its root.

        Returns None when there is nothing to anchor.  Ordering is by creation
        time then id so a batch is reproducible.
        """
        await set_tenant_context(self.db, str(tenant_id))

        rows = (
            await self.db.execute(
                select(DocumentAnchor)
                .where(
                    DocumentAnchor.tenant_id == tenant_id,
                    DocumentAnchor.batch_id.is_(None),
                )
                .order_by(DocumentAnchor.created_at.asc(), DocumentAnchor.id.asc())
                .limit(max_leaves)
            )
        ).scalars().all()

        if not rows:
            return None

        # leaf_hex is already a leaf hash, so use from_leaf_hashes: hashing it
        # again would yield a root no verifier could reproduce.
        tree = MerkleTree.from_leaf_hashes([bytes.fromhex(r.leaf_hex) for r in rows])

        batch = AnchorBatch(
            tenant_id=tenant_id,
            root_hex=tree.root_hex,
            leaf_count=tree.leaf_count,
            status="pending",
        )
        self.db.add(batch)
        await self.db.commit()
        await self.db.refresh(batch)

        # Attach proofs before publishing: if publication fails we retry, and
        # the proofs are already durable and consistent with the root.
        for index, row in enumerate(rows):
            row.batch_id = batch.id
            row.leaf_index = index
            row.proof = tree.proof_for(index).to_json()
        await self.db.commit()

        await self._publish(batch)
        return batch

    async def _publish(self, batch: AnchorBatch) -> bool:
        """Publish a batch root, recording failure without losing the batch."""
        batch.attempt_count += 1
        try:
            receipt = await self._provider.publish(
                batch.root_hex, batch_id=str(batch.id)
            )
        except AnchorUnavailableError as exc:
            # Stay 'pending' so the next sweep retries. The proofs are already
            # valid against the root; only publication is outstanding.
            batch.status = "pending"
            batch.failure_reason = str(exc)
            await self.db.commit()
            logger.warning("Anchor batch %s not published: %s", batch.id, exc)
            return False

        batch.status = "anchored"
        batch.provider = receipt.provider
        batch.ledger_ref = receipt.ledger_ref
        batch.anchored_at = receipt.anchored_at
        batch.failure_reason = None
        batch.receipt = {
            "provider": receipt.provider,
            "ledger_ref": receipt.ledger_ref,
            "root_hex": receipt.root_hex,
            "anchored_at": receipt.anchored_at.isoformat(),
            "metadata": receipt.metadata,
        }
        await self.db.commit()
        logger.info(
            "Anchored batch %s (%d leaves) as %s:%s",
            batch.id,
            batch.leaf_count,
            receipt.provider,
            receipt.ledger_ref,
        )
        return True

    async def retry_pending_batches(self, limit: int = 50) -> int:
        """Re-publish batches whose root was built but never accepted."""
        rows = (
            await self.db.execute(
                select(AnchorBatch)
                .where(AnchorBatch.status == "pending", AnchorBatch.leaf_count > 0)
                .order_by(AnchorBatch.created_at.asc())
                .limit(limit)
            )
        ).scalars().all()

        published = 0
        for batch in rows:
            if await self._publish(batch):
                published += 1
        return published

    # ------------------------------------------------------------------
    # Proof retrieval and verification
    # ------------------------------------------------------------------

    async def proof_for_document(
        self, tenant_id: UUID, document_id: UUID
    ) -> dict | None:
        """Return the anchor proof bundle for a document, or None if unanchored."""
        await set_tenant_context(self.db, str(tenant_id))

        anchor = (
            await self.db.execute(
                select(DocumentAnchor).where(
                    DocumentAnchor.document_id == document_id
                )
            )
        ).scalar_one_or_none()

        if anchor is None:
            return None

        batch = None
        if anchor.batch_id is not None:
            batch = (
                await self.db.execute(
                    select(AnchorBatch).where(AnchorBatch.id == anchor.batch_id)
                )
            ).scalar_one_or_none()

        return {
            "credential_id": str(document_id),
            "leaf_hash": anchor.leaf_hex,
            "leaf_index": anchor.leaf_index,
            "proof": anchor.proof,
            "anchored": bool(batch and batch.status == "anchored"),
            "root_hex": batch.root_hex if batch else None,
            "provider": batch.provider if batch else None,
            "ledger_ref": batch.ledger_ref if batch else None,
            "anchored_at": (
                batch.anchored_at.isoformat() if batch and batch.anchored_at else None
            ),
        }

    async def verify_document(self, tenant_id: UUID, document_id: UUID) -> dict:
        """Recompute the Merkle root for a document and confirm the ledger agrees.

        Two independent checks:
          1. The stored proof reproduces the batch root (integrity of the batch).
          2. The ledger still reports that same root (the anchor was not
             reorganised away or edited after publication).
        """
        bundle = await self.proof_for_document(tenant_id, document_id)
        if bundle is None:
            return {"status": "not_anchored", "verified": False}

        if not bundle["anchored"] or not bundle["proof"] or not bundle["root_hex"]:
            return {"status": "pending_anchor", "verified": False, **bundle}

        proof_ok = verify_inclusion_from_leaf(
            bytes.fromhex(bundle["leaf_hash"]),
            InclusionProof.from_json(bundle["proof"]),
            bundle["root_hex"],
        )

        ledger_root = None
        try:
            if bundle["ledger_ref"]:
                ledger_root = await self._provider.resolve(bundle["ledger_ref"])
        except AnchorUnavailableError as exc:
            logger.warning("Could not resolve ledger ref: %s", exc)

        ledger_ok = ledger_root == bundle["root_hex"] if ledger_root else None

        return {
            "status": "anchored",
            "verified": bool(proof_ok and (ledger_ok is not False)),
            "proof_valid": proof_ok,
            "ledger_agrees": ledger_ok,
            **bundle,
        }
