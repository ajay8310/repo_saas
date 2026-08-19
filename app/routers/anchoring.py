"""
Anchoring endpoints — inclusion proofs and independent verification.

    GET  /api/v1/documents/{credential_id}/anchor   authenticated proof bundle
    POST /api/v1/anchors/verify                     public, offline proof check
    GET  /api/v1/anchors/batches                    tenant anchoring status

The public verify endpoint takes the proof as input rather than looking it up,
so a relying party can check a credential using only the bundle it was handed.
That is the point of anchoring: verification must not require trusting — or even
reaching — this platform.

Requirements: 10.2, 10.3, 5.6
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.dependencies.auth import TokenPayload, get_current_user
from app.middleware.tenant_context import set_tenant_context
from app.models.anchor import AnchorBatch
from app.services.anchoring import (
    AnchoringService,
    InclusionProof,
    get_anchoring_service,
    verify_inclusion_from_leaf,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["anchoring"])


# --- Request / Response models ---


class ProofSibling(BaseModel):
    position: str = Field(..., pattern="^[LR]$")
    hash: str = Field(..., min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")


class ProofBody(BaseModel):
    leaf_index: int = Field(..., ge=0)
    leaf_count: int = Field(..., ge=1)
    siblings: list[ProofSibling] = Field(default_factory=list)


class VerifyAnchorRequest(BaseModel):
    leaf_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
        description="The credential's leaf digest from its proof bundle.",
    )
    root_hex: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern="^[0-9a-f]{64}$",
        description="The anchored Merkle root the proof should reproduce.",
    )
    proof: ProofBody


class VerifyAnchorResponse(BaseModel):
    proof_valid: bool
    computed_root: str
    ledger_ref: str | None
    ledger_agrees: bool | None
    anchored_at: str | None
    message: str


class AnchorBundleResponse(BaseModel):
    credential_id: str
    leaf_hash: str
    leaf_index: int | None
    proof: dict | None
    anchored: bool
    root_hex: str | None
    provider: str | None
    ledger_ref: str | None
    anchored_at: str | None


class BatchResponse(BaseModel):
    batch_id: str
    root_hex: str
    leaf_count: int
    status: str
    provider: str | None
    ledger_ref: str | None
    anchored_at: str | None
    attempt_count: int
    failure_reason: str | None


# --- Endpoints ---


@router.get(
    "/documents/{credential_id}/anchor",
    response_model=AnchorBundleResponse,
    summary="Get the anchor proof bundle for a credential",
)
async def get_document_anchor(
    credential_id: UUID,
    user: TokenPayload = Depends(get_current_user),
    service: AnchoringService = Depends(get_anchoring_service),
) -> AnchorBundleResponse:
    """Return everything needed to verify this credential elsewhere (Req 10.3)."""
    bundle = await service.proof_for_document(user.tenant_id, credential_id)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "NOT_ANCHORED",
                "message": (
                    "No anchor commitment exists for this credential. Anchoring "
                    "runs asynchronously after issuance."
                ),
            },
        )
    return AnchorBundleResponse(**bundle)


@router.post(
    "/anchors/verify",
    response_model=VerifyAnchorResponse,
    summary="Verify an inclusion proof (public)",
)
async def verify_anchor(
    body: VerifyAnchorRequest,
    service: AnchoringService = Depends(get_anchoring_service),
) -> VerifyAnchorResponse:
    """Recompute a Merkle root from a proof bundle.

    Public and unauthenticated by design — a relying party verifying a
    credential is not a tenant of this platform. Nothing here reads tenant data:
    the proof is supplied by the caller, and the only lookup is the ledger
    reference for the claimed root, which is public information.
    """
    proof = InclusionProof.from_json(body.proof.model_dump())

    try:
        leaf = bytes.fromhex(body.leaf_hash)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "INVALID_LEAF", "message": "leaf_hash is not valid hex."},
        )

    proof_valid = verify_inclusion_from_leaf(leaf, proof, body.root_hex)

    # Independently confirm the ledger still reports this root. A valid proof
    # against a root nobody anchored proves nothing about when it existed.
    ledger_ref: str | None = None
    ledger_agrees: bool | None = None
    anchored_at: str | None = None

    batch = (
        await service.db.execute(
            select(AnchorBatch)
            .where(AnchorBatch.root_hex == body.root_hex, AnchorBatch.status == "anchored")
            .limit(1)
        )
    ).scalar_one_or_none()

    if batch is not None:
        ledger_ref = batch.ledger_ref
        anchored_at = batch.anchored_at.isoformat() if batch.anchored_at else None
        if ledger_ref:
            try:
                resolved = await service._provider.resolve(ledger_ref)  # noqa: SLF001
                ledger_agrees = resolved == body.root_hex
            except Exception:  # noqa: BLE001
                logger.warning("Ledger unreachable while verifying %s", ledger_ref)
                ledger_agrees = None

    if not proof_valid:
        message = "Proof does not reproduce the supplied root; credential is not covered by it."
    elif ledger_agrees is True:
        message = "Proof is valid and the ledger confirms the anchored root."
    elif ledger_agrees is False:
        message = "Proof is valid but the ledger reports a different root — investigate."
    elif batch is None:
        message = (
            "Proof is internally consistent, but this root is not anchored here. "
            "Confirm the root against the ledger directly."
        )
    else:
        message = "Proof is valid; the ledger could not be reached to confirm the root."

    return VerifyAnchorResponse(
        proof_valid=proof_valid,
        computed_root=body.root_hex if proof_valid else "",
        ledger_ref=ledger_ref,
        ledger_agrees=ledger_agrees,
        anchored_at=anchored_at,
        message=message,
    )


@router.get(
    "/anchors/batches",
    response_model=list[BatchResponse],
    summary="List anchoring batches for the tenant",
)
async def list_batches(
    limit: int = 50,
    user: TokenPayload = Depends(get_current_user),
    service: AnchoringService = Depends(get_anchoring_service),
) -> list[BatchResponse]:
    """Show anchoring progress, including batches awaiting publication."""
    await set_tenant_context(service.db, str(user.tenant_id))
    rows = (
        await service.db.execute(
            select(AnchorBatch)
            .order_by(AnchorBatch.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
    ).scalars().all()

    return [
        BatchResponse(
            batch_id=str(b.id),
            root_hex=b.root_hex,
            leaf_count=b.leaf_count,
            status=b.status,
            provider=b.provider,
            ledger_ref=b.ledger_ref,
            anchored_at=b.anchored_at.isoformat() if b.anchored_at else None,
            attempt_count=b.attempt_count,
            failure_reason=b.failure_reason,
        )
        for b in rows
    ]
