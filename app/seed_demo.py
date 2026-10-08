"""Idempotent demo seeding for the local/dev stack.

Run as ``python -m app.seed_demo`` (the compose ``seed`` service does this
automatically after migrations). It makes the browser demo work out of the box
and survive a full ``docker compose down/up``:

1. Creates the configured S3 bucket in LocalStack (with the correct region
   LocationConstraint) if it does not exist.
2. Ensures a demo tenant ("Demo University") with an Open Badges issuer profile.
3. Ensures one badge class ("Advanced Python — Demo") with a certificate
   template, a badge image, and one issued-and-public assertion to
   ``jane.learner@example.com`` (the demo beneficiary subject) with a recipient
   photo — so the wallet, certificate download, directory, and analytics all
   have real data.

Everything is guarded so re-running is safe (no duplicates). Only runs when the
environment is development; it is a no-op otherwise.
"""

from __future__ import annotations

import asyncio
import io
import logging

from sqlalchemy import select

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.badge import BadgeClass
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

_DEMO_BENEFICIARY = "jane.learner@example.com"
_DEMO_BADGE_NAME = "Advanced Python — Demo"


def _solid_png(color: tuple[int, int, int], size: tuple[int, int] = (240, 240)) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.ellipse([30, 30, size[0] - 30, size[1] - 30], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _ensure_bucket() -> None:
    import boto3
    from botocore.exceptions import ClientError

    s = get_settings()
    if not s.s3_endpoint_url:
        return  # real AWS — not our job to create buckets
    kwargs = {
        "region_name": s.aws_region,
        "endpoint_url": s.s3_endpoint_url,
        "aws_access_key_id": s.aws_access_key_id or "test",
        "aws_secret_access_key": s.aws_secret_access_key or "test",
    }
    c = boto3.client("s3", **kwargs)
    try:
        c.head_bucket(Bucket=s.s3_bucket_name)
        logger.info("Demo seed: S3 bucket %s already exists", s.s3_bucket_name)
    except ClientError:
        if s.aws_region and s.aws_region != "us-east-1":
            c.create_bucket(
                Bucket=s.s3_bucket_name,
                CreateBucketConfiguration={"LocationConstraint": s.aws_region},
            )
        else:
            c.create_bucket(Bucket=s.s3_bucket_name)
        logger.info("Demo seed: created S3 bucket %s", s.s3_bucket_name)


async def _ensure_tenant(db) -> Tenant:
    tenant = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
    if tenant is None:
        tenant = Tenant(
            namespace="demo-edu",
            name="Demo University",
            domain="demo-edu.example.gov",
            contact_email="registrar@demo-edu.example.gov",
            status="active",
            issuer_name="Demo University",
            issuer_url="https://demo-edu.example.gov",
            issuer_email="badges@demo-edu.example.gov",
        )
        db.add(tenant)
        await db.commit()
        await db.refresh(tenant)
        logger.info("Demo seed: created tenant %s", tenant.id)
    elif tenant.status != "active" or not tenant.issuer_name:
        tenant.status = "active"
        tenant.issuer_name = tenant.issuer_name or tenant.name
        await db.commit()
    return tenant


async def _ensure_badge_and_assertion(db, tenant: Tenant) -> None:
    from app.services.badge_service import BadgeService
    from app.services.certificate_service import CertificateService
    from app.services.issuance_service import IssuanceService
    from app.services.wallet_service import WalletService

    settings = get_settings()
    badge_svc = BadgeService(db=db, settings=settings)

    # Already seeded? Look for our named class under this tenant.
    from app.middleware.tenant_context import set_tenant_context

    await set_tenant_context(db, str(tenant.id))
    existing = (
        await db.execute(
            select(BadgeClass).where(
                BadgeClass.tenant_id == tenant.id,
                BadgeClass.name == _DEMO_BADGE_NAME,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        logger.info("Demo seed: badge class already present (%s)", existing.id)
        return

    badge = await badge_svc.create_badge_class(
        tenant_id=tenant.id,
        name=_DEMO_BADGE_NAME,
        description="Awarded for completing the advanced Python track.",
        criteria_narrative="Pass the proctored assessment with 80% or higher.",
        validity_days=365,
        actor_id="seed",
        actor_role="issuer",
    )
    await badge_svc.update_badge_class(
        tenant_id=tenant.id, badge_class_id=badge.id,
        actor_id="seed", certificate_template="classic",
    )
    try:
        await badge_svc.attach_image(
            tenant_id=tenant.id, badge_class_id=badge.id,
            content=_solid_png((180, 140, 20)), content_type="image/png",
            actor_id="seed",
        )
    except Exception:
        logger.warning("Demo seed: badge image attach skipped", exc_info=True)

    issue_svc = IssuanceService(db=db, settings=settings)
    result = await issue_svc.issue(
        tenant_id=tenant.id, badge_class_id=badge.id,
        beneficiary_id=_DEMO_BENEFICIARY,
        actor_id="seed", actor_role="issuer", notify=False,
    )
    from uuid import UUID

    aid = UUID(result.assertion_id)

    cert_svc = CertificateService(db=db, settings=settings)
    try:
        await cert_svc.upload_recipient_photo(
            tenant_id=tenant.id, assertion_id=aid,
            content=_solid_png((70, 90, 140)), content_type="image/png",
            actor_id="seed",
        )
    except Exception:
        logger.warning("Demo seed: recipient photo skipped", exc_info=True)

    # Make it public + directory-visible so wallet/directory/analytics show it.
    wallet = WalletService(db=db, settings=settings)
    await wallet.set_public(tenant.id, _DEMO_BENEFICIARY, aid, True)
    await badge_svc.set_directory_visibility(
        tenant.id, badge.id, True, actor_id="seed"
    )
    logger.info("Demo seed: issued public assertion %s", aid)


async def seed() -> None:
    settings = get_settings()
    if settings.environment != "development":
        logger.info("Demo seed: skipped (environment=%s)", settings.environment)
        return
    _ensure_bucket()
    async with AsyncSessionLocal() as db:
        tenant = await _ensure_tenant(db)
        await _ensure_badge_and_assertion(db, tenant)
    logger.info("Demo seed: complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(seed())
