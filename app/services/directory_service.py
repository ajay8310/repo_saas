"""Public directory (U3 — S14, BR-D1..D3, BR-P1/P2).

Read-only public views over badge classes and assertions:

* ``list_classes`` — the catalog of ``directory_visible=true`` classes.
* ``list_public_earners`` — masked earners holding a ``public=true`` assertion of
  a class.
* ``earner_profile`` — a masked earner's public badges.

Every surface filters to public/visible rows only (BR-P1), and earner identities
are always masked (BR-P2, Q5=A). Pagination is keyset/seek-based on
``(created_at, id)`` / ``(issued_at, id)`` so it scales past 10M rows (BR-D3).

These are unauthenticated reads. There is no JWT tenant, so the service sets the
tenant context from the resolved row's tenant and relies on the public filters;
callers pass the tenant explicitly for directory listings.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.session import get_db
from app.middleware.tenant_context import set_tenant_context
from app.models.badge import BadgeAssertion, BadgeClass
from app.services.identity_masking import mask_identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DirectoryClass:
    badge_class_id: str
    name: str
    description: str | None
    criteria_narrative: str | None
    image_s3_key: str | None


@dataclass(frozen=True, slots=True)
class PublicEarner:
    display_name: str
    assertion_id: str
    issued_at: str | None


@dataclass(frozen=True, slots=True)
class EarnerProfile:
    display_name: str
    badges: list[dict] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Page:
    items: list
    next_cursor: str | None


class DirectoryService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ------------------------------------------------------------------
    # Catalog (BR-D1)
    # ------------------------------------------------------------------

    async def list_classes(
        self, tenant_id: UUID, cursor: str | None = None, limit: int | None = None
    ) -> Page:
        """List directory-visible, active badge classes for a tenant (keyset)."""
        limit = self._clamp(limit)
        await set_tenant_context(self.db, str(tenant_id))

        stmt = select(BadgeClass).where(
            BadgeClass.directory_visible.is_(True),
            BadgeClass.status == "active",
        )
        stmt = self._apply_keyset(stmt, BadgeClass.created_at, BadgeClass.id, cursor)
        stmt = stmt.order_by(BadgeClass.created_at.desc(), BadgeClass.id.desc()).limit(limit + 1)

        rows = list((await self.db.execute(stmt)).scalars().all())
        items, next_cursor = self._paginate(
            rows, limit, lambda c: (c.created_at, c.id)
        )
        return Page(
            items=[
                DirectoryClass(
                    badge_class_id=str(c.id),
                    name=c.name,
                    description=c.description,
                    criteria_narrative=c.criteria_narrative,
                    image_s3_key=c.image_s3_key,
                )
                for c in items
            ],
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # Public earners (BR-D2)
    # ------------------------------------------------------------------

    async def list_public_earners(
        self,
        tenant_id: UUID,
        badge_class_id: UUID,
        cursor: str | None = None,
        limit: int | None = None,
    ) -> Page:
        """List masked earners with a public, active assertion of a class."""
        limit = self._clamp(limit)
        await set_tenant_context(self.db, str(tenant_id))

        stmt = select(BadgeAssertion).where(
            BadgeAssertion.badge_class_id == badge_class_id,
            BadgeAssertion.public.is_(True),
            BadgeAssertion.status == "active",
        )
        stmt = self._apply_keyset(stmt, BadgeAssertion.issued_at, BadgeAssertion.id, cursor)
        stmt = stmt.order_by(BadgeAssertion.issued_at.desc(), BadgeAssertion.id.desc()).limit(limit + 1)

        rows = list((await self.db.execute(stmt)).scalars().all())
        items, next_cursor = self._paginate(rows, limit, lambda a: (a.issued_at, a.id))
        return Page(
            items=[
                PublicEarner(
                    display_name=mask_identity(a.beneficiary_id),
                    assertion_id=str(a.id),
                    issued_at=a.issued_at.isoformat() if a.issued_at else None,
                )
                for a in items
            ],
            next_cursor=next_cursor,
        )

    # ------------------------------------------------------------------
    # Earner profile
    # ------------------------------------------------------------------

    async def earner_profile(
        self, tenant_id: UUID, beneficiary_id: str
    ) -> EarnerProfile | None:
        """A masked earner's public badges within a tenant (BR-P1/P2)."""
        await set_tenant_context(self.db, str(tenant_id))
        result = await self.db.execute(
            select(BadgeAssertion)
            .where(
                BadgeAssertion.beneficiary_id == beneficiary_id,
                BadgeAssertion.public.is_(True),
                BadgeAssertion.status == "active",
            )
            .order_by(BadgeAssertion.issued_at.desc())
            .limit(200)
        )
        assertions = list(result.scalars().all())
        if not assertions:
            return None

        class_ids = {a.badge_class_id for a in assertions}
        classes = {
            c.id: c
            for c in (
                await self.db.execute(select(BadgeClass).where(BadgeClass.id.in_(class_ids)))
            ).scalars().all()
        }
        badges = [
            {
                "assertion_id": str(a.id),
                "badge_name": classes[a.badge_class_id].name if a.badge_class_id in classes else "Badge",
                "issued_at": a.issued_at.isoformat() if a.issued_at else None,
            }
            for a in assertions
        ]
        return EarnerProfile(display_name=mask_identity(beneficiary_id), badges=badges)

    # ------------------------------------------------------------------
    # Keyset helpers
    # ------------------------------------------------------------------

    def _clamp(self, limit: int | None) -> int:
        default = self.settings.directory_page_size_default
        maximum = self.settings.directory_page_size_max
        if limit is None or limit <= 0:
            return default
        return min(limit, maximum)

    def _apply_keyset(self, stmt, ts_col, id_col, cursor: str | None):
        """Seek past the cursor on (ts desc, id desc)."""
        if not cursor:
            return stmt
        decoded = _decode_cursor(cursor)
        if decoded is None:
            return stmt
        ts, last_id = decoded
        # (ts, id) strictly less than the cursor, matching the desc ordering.
        return stmt.where(
            (ts_col < ts) | ((ts_col == ts) & (id_col < last_id))
        )

    def _paginate(self, rows: list, limit: int, key):
        """Trim the +1 sentinel row and build the next cursor."""
        if len(rows) > limit:
            page = rows[:limit]
            ts, last_id = key(page[-1])
            return page, _encode_cursor(ts, last_id)
        return rows, None


def _encode_cursor(ts: datetime, last_id: UUID) -> str:
    raw = json.dumps({"ts": ts.isoformat(), "id": str(last_id)})
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime, UUID] | None:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        data = json.loads(raw)
        return datetime.fromisoformat(data["ts"]), UUID(data["id"])
    except Exception:
        logger.debug("Bad directory cursor", exc_info=True)
        return None


async def get_directory_service(db: AsyncSession = Depends(get_db)) -> DirectoryService:
    return DirectoryService(db=db, settings=get_settings())
