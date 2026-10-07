"""Public, unauthenticated badge endpoints (S13, FR-13).

Serves the hosted Open Badges 2.0 artifacts that make a badge verifiable by any
third party: the assertion JSON, its badge class, and the issuer profile. These
are the verification target referenced by ``verification: {"type":
"HostedBadge"}`` in the assertion.

Design decisions honoured here:

* **Unauthenticated (Q2=A)** — a dedicated public router, mounted under
  ``/api/v1/public/badges`` so the tenant-context middleware skips it.
* **Per-IP throttle (public routes)** — a lightweight Redis fixed-window limiter
  keyed by client IP, independent of the per-tenant authenticated limiter.
* **Short-TTL cache (~60s)** — hosted JSON is cached in Redis to absorb
  verification traffic spikes; revocation/visibility changes converge within the
  TTL.
* **Uniform 404 (Q7=A)** — anything not currently public (never published,
  hidden, deleted-from-wallet, or belonging to an inactive class) returns an
  indistinguishable 404 so the endpoint leaks nothing about private badges.
* **Revoked but public stays 200 (Q3=A)** — a revoked assertion still resolves
  and reports ``revoked: true``; it is only removed from the directory.

Because these routes are unauthenticated, RLS cannot key off a JWT tenant. The
service layer therefore sets tenant context explicitly from the row it resolves
by primary key, and only ever exposes rows whose ``public`` flag is set.
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.services.directory_service import DirectoryService, get_directory_service
from app.services.public_badge_service import (
    PublicBadgeService,
    get_public_badge_service,
)
from app.services.share_service import ShareService, get_share_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/public/badges", tags=["public-badges"])

_NOT_FOUND = {"code": "NOT_FOUND", "message": "Badge not found."}


async def _throttle(request: Request) -> None:
    """Per-IP fixed-window rate limit for public endpoints.

    Fails open if Redis is unavailable — availability of public verification is
    prioritised over strict throttling, mirroring the tenant-status check.
    """
    from app.config import get_settings

    settings = get_settings()
    client_ip = request.client.host if request.client else "unknown"
    try:
        from app.db.redis import get_redis_client

        redis = get_redis_client()
        key = f"public_badge_rl:{client_ip}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, settings.public_rate_limit_window_seconds)
        if count > settings.public_rate_limit_per_ip:
            raise HTTPException(
                status_code=429,
                detail={"code": "RATE_LIMITED", "message": "Too many requests."},
                headers={"Retry-After": str(settings.public_rate_limit_window_seconds)},
            )
    except HTTPException:
        raise
    except Exception:
        logger.debug("Public badge throttle unavailable; failing open", exc_info=True)


@router.get("/assertions/{assertion_id}")
async def get_hosted_assertion(
    assertion_id: UUID,
    request: Request,
    service: PublicBadgeService = Depends(get_public_badge_service),
    _: None = Depends(_throttle),
) -> dict:
    """Return the hosted Open Badges 2.0 Assertion JSON (S13, FR-13).

    404 if the assertion is not currently public. A revoked-but-public
    assertion returns 200 with ``revoked: true``.
    """
    doc = await service.get_hosted_assertion(assertion_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    # Record a verification event (best-effort).
    await service.record_verification(assertion_id)
    return doc


@router.get("/classes/{badge_class_id}")
async def get_hosted_badge_class(
    badge_class_id: UUID,
    request: Request,
    service: PublicBadgeService = Depends(get_public_badge_service),
    _: None = Depends(_throttle),
) -> dict:
    """Return the hosted Open Badges 2.0 BadgeClass JSON."""
    doc = await service.get_hosted_badge_class(badge_class_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return doc


@router.get("/issuers/{tenant_id}")
async def get_hosted_issuer(
    tenant_id: UUID,
    request: Request,
    service: PublicBadgeService = Depends(get_public_badge_service),
    _: None = Depends(_throttle),
) -> dict:
    """Return the hosted Open Badges 2.0 Issuer profile JSON."""
    doc = await service.get_hosted_issuer(tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return doc


@router.get("/issuers/{tenant_id}/key")
async def get_issuer_public_key(
    tenant_id: UUID,
    request: Request,
    service: PublicBadgeService = Depends(get_public_badge_service),
    _: None = Depends(_throttle),
) -> dict:
    """Return the issuer's published RS256 signing public key (U4 Q7).

    Verifiers use this to check the signature embedded in a certificate.
    """
    doc = await service.get_issuer_public_key(tenant_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return doc


# ---------------------------------------------------------------------------
# Public directory (U3 — S14)
# ---------------------------------------------------------------------------


@router.get("/directory/{tenant_id}")
async def list_directory(
    tenant_id: UUID,
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    service: DirectoryService = Depends(get_directory_service),
    _: None = Depends(_throttle),
) -> dict:
    """List a tenant's directory-visible badge classes (keyset paginated)."""
    page = await service.list_classes(tenant_id, cursor=cursor, limit=limit)
    return {
        "items": [c.__dict__ for c in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/directory/{tenant_id}/classes/{badge_class_id}/earners")
async def list_class_earners(
    tenant_id: UUID,
    badge_class_id: UUID,
    request: Request,
    cursor: str | None = None,
    limit: int | None = None,
    service: DirectoryService = Depends(get_directory_service),
    _: None = Depends(_throttle),
) -> dict:
    """List masked public earners of a badge class (keyset paginated, BR-D2)."""
    page = await service.list_public_earners(
        tenant_id, badge_class_id, cursor=cursor, limit=limit
    )
    return {
        "items": [e.__dict__ for e in page.items],
        "next_cursor": page.next_cursor,
    }


@router.get("/directory/{tenant_id}/earners/{beneficiary_ref}")
async def earner_profile(
    tenant_id: UUID,
    beneficiary_ref: str,
    request: Request,
    service: DirectoryService = Depends(get_directory_service),
    _: None = Depends(_throttle),
) -> dict:
    """A masked earner's public badges within a tenant. 404 if none public."""
    profile = await service.earner_profile(tenant_id, beneficiary_ref)
    if profile is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {"display_name": profile.display_name, "badges": profile.badges}


# ---------------------------------------------------------------------------
# Sharing (U3 — S12)
# ---------------------------------------------------------------------------


@router.get("/assertions/{assertion_id}/share")
async def share_assertion(
    assertion_id: UUID,
    request: Request,
    channel: str = "link",
    service: ShareService = Depends(get_share_service),
    _: None = Depends(_throttle),
) -> dict:
    """Build share targets (link + LinkedIn + Open Graph) for a public badge.

    404 when the badge is not public or revoked (BR-P1/P6). Records a ``shared``
    event tagged with the channel (BR-P5).
    """
    target = await service.build_share(assertion_id, channel)
    if target is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return {
        "assertion_id": target.assertion_id,
        "channel": target.channel,
        "share_url": target.share_url,
        "linkedin_url": target.linkedin_url,
        "open_graph": target.open_graph,
    }
