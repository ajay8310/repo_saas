"""Recipient wallet service (U2 — S7, S9, S10, S11, S12).

The wallet is the beneficiary-facing view over their own ``BadgeAssertion`` rows.
U2 adds no new tables: it manages the earner-controlled flags on U1's
``badge_assertions`` (``accepted`` / ``hidden`` / ``public``) and returns wallet
items enriched with a badge-class summary.

Business rules (U2 functional design):

* **BR-W1 own-only** — a beneficiary sees only assertions whose ``beneficiary_id``
  matches their authenticated identity. Combined with RLS this is defence in depth.
* **BR-W2 hide** — hidden assertions are excluded from the default listing but
  remain the earner's and can be unhidden.
* **BR-W3 private-by-default** — assertions are ``public=false`` at issuance;
  becoming public is an explicit earner action.
* **BR-W4 delete-from-wallet (Q4=B)** — a soft delist: sets ``hidden=true`` and
  ``public=false``. The assertion is never destroyed, so its hosted URL stays
  verifiable; it simply leaves the earner's active wallet and the directory.
* **BR-W5 revoked cannot be published** — attempting to make a revoked assertion
  public is rejected (409).
* **BR-W6 publish event** — flipping to public records a ``published`` analytics
  event (U3 aggregates it).
* **BR-W7 not-owned → None** — any assertion the caller doesn't own resolves to
  ``None`` so the router returns an indistinguishable 404.

Persistence follows the established conventions: RLS via ``set_tenant_context``,
events inside the caller's transaction, single-table queries (no joins — the
class summary is a second keyed lookup).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.services.badge_event_service import BadgeEventService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WalletItem:
    """A single wallet entry: assertion state + badge-class summary."""

    assertion_id: str
    badge_class_id: str
    badge_name: str
    badge_description: str | None
    image_s3_key: str | None
    status: str
    issued_at: str | None
    expires_at: str | None
    accepted: bool
    hidden: bool
    public: bool
    revoked_at: str | None
    public_url: str


class WalletService:
    """Earner-facing management of their own badge assertions."""

    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._events = BadgeEventService(db)

    # ------------------------------------------------------------------
    # Listing (S7)
    # ------------------------------------------------------------------

    async def list_wallet(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        include_hidden: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[WalletItem]:
        """Return the beneficiary's own assertions, newest first (S7, BR-W1/W2)."""
        await set_tenant_context(self.db, str(tenant_id))

        stmt = select(BadgeAssertion).where(
            BadgeAssertion.beneficiary_id == beneficiary_id
        )
        if not include_hidden:
            stmt = stmt.where(BadgeAssertion.hidden.is_(False))
        stmt = stmt.order_by(BadgeAssertion.issued_at.desc()).limit(limit).offset(offset)

        result = await self.db.execute(stmt)
        assertions = list(result.scalars().all())
        if not assertions:
            return []

        # Second keyed lookup for class summaries (no join).
        class_ids = {a.badge_class_id for a in assertions}
        class_result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id.in_(class_ids))
        )
        classes = {c.id: c for c in class_result.scalars().all()}

        return [self._to_item(a, classes.get(a.badge_class_id)) for a in assertions]

    # ------------------------------------------------------------------
    # Visibility (S11, BR-W3/W5/W6)
    # ------------------------------------------------------------------

    async def set_public(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        assertion_id: UUID,
        public: bool,
    ) -> WalletItem | None:
        """Make an assertion public or private (S11).

        A revoked assertion cannot be made public (BR-W5 → raises). Transition to
        public records a ``published`` event (BR-W6). Returns ``None`` if the
        caller does not own the assertion (BR-W7).
        """
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_own(assertion_id, beneficiary_id)
        if assertion is None:
            return None

        if public and assertion.status == "revoked":
            raise WalletConflictError("a revoked badge cannot be made public")

        was_public = assertion.public
        assertion.public = public

        if public and not was_public:
            self._events.record(
                tenant_id=tenant_id,
                event_type="published",
                badge_class_id=assertion.badge_class_id,
                assertion_id=assertion_id,
                channel="wallet",
            )

        await self.db.commit()
        await self.db.refresh(assertion)
        return self._to_item(assertion, await self._get_class(assertion.badge_class_id))

    # ------------------------------------------------------------------
    # Hide / unhide (S9, BR-W2)
    # ------------------------------------------------------------------

    async def set_hidden(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        assertion_id: UUID,
        hidden: bool,
    ) -> WalletItem | None:
        """Hide or unhide an assertion in the earner's wallet (S9)."""
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_own(assertion_id, beneficiary_id)
        if assertion is None:
            return None
        assertion.hidden = hidden
        await self.db.commit()
        await self.db.refresh(assertion)
        return self._to_item(assertion, await self._get_class(assertion.badge_class_id))

    # ------------------------------------------------------------------
    # Delete from wallet (S10, BR-W4 / Q4=B soft delist)
    # ------------------------------------------------------------------

    async def delete_from_wallet(
        self,
        tenant_id: UUID,
        beneficiary_id: str,
        assertion_id: UUID,
    ) -> bool:
        """Soft-remove an assertion from the wallet (S10, BR-W4).

        Sets ``hidden=true`` and ``public=false``. The row is never destroyed so
        the hosted assertion remains verifiable; it only leaves the active wallet
        and the public directory. Returns False if not owned (BR-W7).
        """
        await set_tenant_context(self.db, str(tenant_id))
        assertion = await self._get_own(assertion_id, beneficiary_id)
        if assertion is None:
            return False
        assertion.hidden = True
        assertion.public = False
        await self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Share entry point (S12)
    # ------------------------------------------------------------------

    def public_url(self, assertion_id: UUID) -> str:
        """Public hosted-assertion URL used as the share target (S12)."""
        return (
            f"{self.settings.public_base_url}"
            f"/api/v1/public/badges/assertions/{assertion_id}"
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _get_own(
        self, assertion_id: UUID, beneficiary_id: str
    ) -> BadgeAssertion | None:
        """Resolve an assertion only if it belongs to *beneficiary_id* (BR-W1/W7)."""
        result = await self.db.execute(
            select(BadgeAssertion).where(
                BadgeAssertion.id == assertion_id,
                BadgeAssertion.beneficiary_id == beneficiary_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()

    def _to_item(
        self, assertion: BadgeAssertion, badge_class: BadgeClass | None
    ) -> WalletItem:
        return WalletItem(
            assertion_id=str(assertion.id),
            badge_class_id=str(assertion.badge_class_id),
            badge_name=badge_class.name if badge_class else "Unknown Badge",
            badge_description=badge_class.description if badge_class else None,
            image_s3_key=badge_class.image_s3_key if badge_class else None,
            status=assertion.status,
            issued_at=assertion.issued_at.isoformat() if assertion.issued_at else None,
            expires_at=assertion.expires_at.isoformat() if assertion.expires_at else None,
            accepted=assertion.accepted,
            hidden=assertion.hidden,
            public=assertion.public,
            revoked_at=assertion.revoked_at.isoformat() if assertion.revoked_at else None,
            public_url=self.public_url(assertion.id),
        )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WalletConflictError(Exception):
    """Raised when an operation conflicts with assertion state (e.g. revoked)."""


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


async def get_wallet_service(db: AsyncSession = Depends(get_db)) -> WalletService:
    return WalletService(db=db, settings=get_settings())
