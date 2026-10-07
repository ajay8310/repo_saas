"""Badge sharing (U3 — S12, BR-P3..P6).

Builds share targets for a *public* badge assertion and records a ``shared``
analytics event tagged with the channel. Everything is derived from the badge's
own fields — no external API or account (BR-P4).

A non-public or revoked assertion is not shareable: the methods return ``None``
so the router answers a uniform 404 (BR-P1/P6).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote, urlencode
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

# Channels we tag share URLs with (free-form, but these are the known buttons).
KNOWN_CHANNELS: frozenset[str] = frozenset(
    {"linkedin", "twitter", "facebook", "email", "link"}
)


@dataclass(frozen=True, slots=True)
class ShareTarget:
    """A share payload for one assertion."""

    assertion_id: str
    channel: str
    share_url: str
    linkedin_url: str
    open_graph: dict


class ShareService:
    def __init__(self, db: AsyncSession, settings: Settings) -> None:
        self.db = db
        self.settings = settings
        self._events = BadgeEventService(db)

    async def build_share(
        self, assertion_id: UUID, channel: str
    ) -> ShareTarget | None:
        """Build share targets for a public assertion and record the event.

        Returns ``None`` when the assertion is missing, not public, or revoked —
        the router maps that to 404 (BR-P1/P6).
        """
        channel = (channel or "link").lower()
        assertion = await self._resolve(assertion_id)
        if assertion is None or not assertion.public or assertion.status == "revoked":
            return None

        badge_class = await self._get_class(assertion.badge_class_id)

        public_url = self._public_url(assertion_id)
        share_url = f"{public_url}?{urlencode({'channel': channel})}"
        og = self._open_graph(public_url, badge_class)

        # Record the share with its channel (BR-P5). Tenant scope + commit.
        await set_tenant_context(self.db, str(assertion.tenant_id))
        self._events.record(
            tenant_id=assertion.tenant_id,
            event_type="shared",
            badge_class_id=assertion.badge_class_id,
            assertion_id=assertion_id,
            channel=channel,
        )
        await self.db.commit()

        return ShareTarget(
            assertion_id=str(assertion_id),
            channel=channel,
            share_url=share_url,
            linkedin_url=self._linkedin_url(share_url),
            open_graph=og,
        )

    # ------------------------------------------------------------------
    # URL / meta builders (pure)
    # ------------------------------------------------------------------

    def _public_url(self, assertion_id: UUID) -> str:
        return (
            f"{self.settings.public_base_url}"
            f"/api/v1/public/badges/assertions/{assertion_id}"
        )

    def _linkedin_url(self, target_url: str) -> str:
        """LinkedIn 'share by URL' deep link (no API/account) (BR-P4)."""
        return f"https://www.linkedin.com/sharing/share-offsite/?url={quote(target_url, safe='')}"

    def _open_graph(self, url: str, badge_class: BadgeClass | None) -> dict:
        """Open Graph meta from badge fields only (BR-P3)."""
        title = badge_class.name if badge_class else "Verified Badge"
        description = (
            (badge_class.description if badge_class and badge_class.description else "")
            or "A verified digital badge."
        )
        return {
            "og:title": title,
            "og:description": description,
            "og:type": "website",
            "og:url": url,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _resolve(self, assertion_id: UUID) -> BadgeAssertion | None:
        result = await self.db.execute(
            select(BadgeAssertion).where(BadgeAssertion.id == assertion_id)
        )
        assertion = result.scalar_one_or_none()
        if assertion is not None:
            await set_tenant_context(self.db, str(assertion.tenant_id))
        return assertion

    async def _get_class(self, badge_class_id: UUID) -> BadgeClass | None:
        result = await self.db.execute(
            select(BadgeClass).where(BadgeClass.id == badge_class_id)
        )
        return result.scalar_one_or_none()


def parse_channel_from_share_url(share_url: str) -> str | None:
    """Extract the ``channel`` query param from a share URL (round-trip helper)."""
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(share_url).query)
    values = qs.get("channel")
    return values[0] if values else None


async def get_share_service(db: AsyncSession = Depends(get_db)) -> ShareService:
    return ShareService(db=db, settings=get_settings())
