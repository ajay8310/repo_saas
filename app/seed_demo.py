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


def _badge_png(size: int = 512, label: str = "EXCELLENCE") -> bytes:
    """Render a premium, award-quality medallion badge as a transparent PNG.

    Pure Pillow (no extra deps): rendered at 4x and downscaled with LANCZOS for
    crisp anti-aliasing. Composition: soft drop shadow, a beveled gold rim built
    from a radial gradient, a fine sunburst field, a navy enamel centre with a
    radial sheen, a laurel wreath framing a faceted star, and a draped ribbon
    banner carrying the *label*.
    """
    import math

    from PIL import Image, ImageDraw, ImageFilter

    SS = 4
    S = size * SS
    cx = cy = S / 2

    # Palette.
    GOLD_HI = (247, 223, 138)
    GOLD = (201, 162, 39)
    GOLD_LO = (138, 101, 18)
    NAVY_HI = (46, 83, 170)
    NAVY = (23, 52, 125)
    NAVY_LO = (11, 26, 74)
    CREAM = (255, 250, 235)

    # Vertical layout budget: medallion sits in the upper area, ribbon below.
    med_cy = S * 0.44
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    def _lerp(a, b, t):
        return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

    def _radial(radius, inner_rgb, outer_rgb, inner_r=0.0):
        """A square RGB radial-gradient tile of diameter 2*radius."""
        d = int(radius * 2)
        g = Image.new("RGB", (d, d))
        px = g.load()
        for yy in range(d):
            dy = yy - radius
            for xx in range(d):
                dx = xx - radius
                dist = math.hypot(dx, dy) / radius
                t = 0.0 if dist <= inner_r else min(1.0, (dist - inner_r) / (1 - inner_r))
                px[xx, yy] = _lerp(inner_rgb, outer_rgb, t)
        return g

    def _disc_mask(radius, feather=0.0):
        d = int(radius * 2)
        m = Image.new("L", (d, d), 0)
        dr = ImageDraw.Draw(m)
        dr.ellipse([0, 0, d - 1, d - 1], fill=255)
        if feather:
            m = m.filter(ImageFilter.GaussianBlur(feather))
        return m

    def _paste_disc(radius, inner_rgb, outer_rgb, inner_r=0.0, cx_=cx, cy_=None):
        cy_ = med_cy if cy_ is None else cy_
        grad = _radial(radius, inner_rgb, outer_rgb, inner_r)
        mask = _disc_mask(radius)
        base.paste(grad, (int(cx_ - radius), int(cy_ - radius)), mask)

    draw = ImageDraw.Draw(base)
    r_out = S * 0.345

    # 1) Soft drop shadow under the medallion.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).ellipse(
        [cx - r_out, med_cy - r_out + S * 0.02, cx + r_out, med_cy + r_out + S * 0.04],
        fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(S * 0.025))
    base.alpha_composite(shadow)

    # 2) Ribbon banner BELOW the medallion (drawn first; medallion sits above it).
    _draw_ribbon_banner(draw, cx, med_cy + r_out * 0.74, S * 0.56, S * 0.15, label,
                        NAVY_HI, NAVY, NAVY_LO, GOLD_HI, S)

    # 3) Beveled gold rim: outer gold gradient disc + top sheen + inner groove.
    _paste_disc(r_out, GOLD_HI, GOLD_LO, inner_r=0.0)
    sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).ellipse(
        [cx - r_out * 0.98, med_cy - r_out * 0.98, cx + r_out * 0.98, med_cy - r_out * 0.1],
        fill=(255, 255, 255, 70))
    sheen = sheen.filter(ImageFilter.GaussianBlur(S * 0.02))
    base.alpha_composite(Image.composite(
        sheen, Image.new("RGBA", (S, S), (0, 0, 0, 0)),
        _ring_mask(S, cx, med_cy, r_out, r_out * 0.84)))
    _paste_disc(r_out * 0.84, GOLD_LO, GOLD, inner_r=0.0)

    # 4) Sunburst field inside the rim (fine alternating gold rays), clipped.
    r_field = r_out * 0.80
    rays = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rdraw = ImageDraw.Draw(rays)
    for i in range(72):
        a0 = math.radians(i * 5)
        a1 = math.radians(i * 5 + 2.5)
        col = GOLD_HI if i % 2 == 0 else GOLD
        rdraw.polygon(
            [(cx, med_cy),
             (cx + r_out * math.cos(a0), med_cy + r_out * math.sin(a0)),
             (cx + r_out * math.cos(a1), med_cy + r_out * math.sin(a1))],
            fill=col + (255,))
    base.alpha_composite(Image.composite(
        rays, Image.new("RGBA", (S, S), (0, 0, 0, 0)),
        _disc_full_mask(S, cx, med_cy, r_field)))
    draw.ellipse([cx - r_field, med_cy - r_field, cx + r_field, med_cy + r_field],
                 outline=GOLD_LO + (255,), width=int(S * 0.008))

    # 5) Navy enamel centre with radial sheen + gold keylines.
    r_centre = r_out * 0.58
    _paste_disc(r_centre, NAVY_HI, NAVY_LO, inner_r=0.12)
    draw.ellipse([cx - r_centre, med_cy - r_centre, cx + r_centre, med_cy + r_centre],
                 outline=GOLD_HI + (255,), width=int(S * 0.014))
    rc2 = r_centre * 0.92
    draw.ellipse([cx - rc2, med_cy - rc2, cx + rc2, med_cy + rc2],
                 outline=GOLD + (210,), width=int(S * 0.004))

    # 6) Faceted central star (slightly raised).
    _draw_faceted_star(draw, cx, med_cy - r_centre * 0.08, r_centre * 0.58,
                       GOLD_HI, GOLD, GOLD_LO)

    # 7) Two clean laurel branches arcing up from the base to frame the star.
    _draw_laurel_branch(draw, cx, med_cy, r_centre, -1, GOLD_HI, GOLD, GOLD_LO)
    _draw_laurel_branch(draw, cx, med_cy, r_centre, +1, GOLD_HI, GOLD, GOLD_LO)

    out = base.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def _disc_full_mask(S, cx, cy, r):
    from PIL import Image, ImageDraw

    m = Image.new("L", (S, S), 0)
    ImageDraw.Draw(m).ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    return m


def _ring_mask(S, cx, cy, r_out, r_in):
    from PIL import Image, ImageDraw

    m = Image.new("L", (S, S), 0)
    dr = ImageDraw.Draw(m)
    dr.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill=255)
    dr.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=0)
    return m


def _draw_faceted_star(draw, cx, cy, r, hi, mid, lo, points: int = 5) -> None:
    import math

    outer, inner = r, r * 0.42
    tips = []
    for i in range(points * 2):
        ang = math.pi * i / points - math.pi / 2
        rad = outer if i % 2 == 0 else inner
        tips.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    # Base star.
    draw.polygon(tips, fill=mid + (255,))
    # Facets: each outer tip gets a light/dark half for a 3D cut look.
    for i in range(points):
        tip = tips[i * 2]
        left = tips[(i * 2 - 1) % (points * 2)]
        right = tips[(i * 2 + 1) % (points * 2)]
        draw.polygon([tip, left, (cx, cy)], fill=hi + (255,))
        draw.polygon([tip, right, (cx, cy)], fill=lo + (255,))
    # Small bright centre.
    draw.ellipse([cx - r * 0.12, cy - r * 0.12, cx + r * 0.12, cy + r * 0.12], fill=hi + (255,))


def _draw_laurel_branch(draw, cx, cy, r_centre, side, hi, mid, lo) -> None:
    """One laurel half-wreath: a smooth stem arc up the side with almond leaves.

    ``side`` is -1 (left) or +1 (right). The stem follows an arc just inside the
    gold keyline from the base (bottom) up to the shoulder; leaves are drawn as
    almond shapes (two arcs) alternating light/dark, pointing up along the stem.
    """
    import math

    arc_r = r_centre * 0.82
    # Sweep from the base (~95deg) up to the shoulder (~165deg).
    a_lo, a_hi = math.radians(96), math.radians(166)
    steps = 40
    stem = [
        (cx + side * arc_r * math.cos(a_lo + (a_hi - a_lo) * t / steps),
         cy + arc_r * math.sin(a_lo + (a_hi - a_lo) * t / steps))
        for t in range(steps + 1)
    ]
    # Draw the stem.
    draw.line(stem, fill=lo + (255,), width=max(2, int(r_centre * 0.03)))

    n = 6
    for k in range(n):
        t = (k + 0.5) / n
        ang = a_lo + (a_hi - a_lo) * t
        bx = cx + side * arc_r * math.cos(ang)
        by = cy + arc_r * math.sin(ang)
        # leaf direction: tangent to the arc, pointing up the wreath
        tang = ang + math.pi / 2
        dx = -side * math.cos(tang)
        dy = -math.sin(tang)
        length = r_centre * (0.34 - 0.03 * k)
        width = r_centre * 0.09
        # perpendicular
        px, py = -dy, dx
        tip = (bx + dx * length, by + dy * length)
        mid_l = (bx + px * width, by + py * width)
        mid_r = (bx - px * width, by - py * width)
        base = (bx - dx * length * 0.15, by - dy * length * 0.15)
        draw.polygon([base, mid_l, tip], fill=(hi if k % 2 == 0 else mid) + (255,))
        draw.polygon([base, mid_r, tip], fill=(mid if k % 2 == 0 else lo) + (255,))
    # Berry at the base where the two branches meet.
    bb = r_centre * 0.045
    draw.ellipse([cx - bb, cy + arc_r * math.sin(a_lo) - bb,
                  cx + bb, cy + arc_r * math.sin(a_lo) + bb], fill=hi + (255,))


def _draw_ribbon_banner(draw, cx, top_y, w, h, text, hi, mid, lo, text_color, S) -> None:

    from PIL import ImageFont

    # Two angled tails behind the banner.
    tail_w = w * 0.22
    for sign in (-1, 1):
        x = cx + sign * w * 0.34
        draw.polygon(
            [(x - tail_w / 2, top_y - h * 0.2), (x + tail_w / 2, top_y - h * 0.2),
             (x + tail_w / 2 + sign * w * 0.10, top_y + h * 1.15),
             (x + sign * w * 0.10, top_y + h * 0.92),
             (x - tail_w / 2 + sign * w * 0.10, top_y + h * 1.15)],
            fill=lo + (255,),
        )
    # Main banner with folded ends (darker fold shading).
    left, right = cx - w / 2, cx + w / 2
    fold = w * 0.07
    draw.polygon([(left, top_y), (left + fold, top_y - h * 0.22),
                  (left + fold, top_y + h), (left, top_y + h * 1.2)], fill=lo + (255,))
    draw.polygon([(right, top_y), (right - fold, top_y - h * 0.22),
                  (right - fold, top_y + h), (right, top_y + h * 1.2)], fill=lo + (255,))
    draw.polygon([(left + fold, top_y - h * 0.08), (right - fold, top_y - h * 0.08),
                  (right - fold, top_y + h * 0.92), (left + fold, top_y + h * 0.92)],
                 fill=mid + (255,))
    # Top highlight stripe on the banner.
    draw.rectangle([left + fold, top_y - h * 0.08, right - fold, top_y + h * 0.14],
                   fill=hi + (120,))

    # Centered label text.
    txt = (text or "").upper()[:22]
    if txt:
        fs = int(h * 0.5)
        font = None
        for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(name, fs)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), txt, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text((cx - tw / 2, top_y + h * 0.42 - th / 2), txt, font=font,
                      fill=text_color + (255,))
        except Exception:
            draw.text((cx - len(txt) * fs * 0.28, top_y + h * 0.2), txt, fill=text_color + (255,))


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
        # The DB rows survive a restart but LocalStack S3 may have been reset,
        # leaving the image/photo keys pointing at missing objects. Refresh the
        # medallion badge image and the demo recipient photo so the certificate
        # embeds all three images (badge + photo + QR) and the baked PNG works.
        await _ensure_badge_image(badge_svc, tenant.id, existing)
        await _ensure_recipient_photo(db, tenant.id, existing.id, settings)
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
            content=_badge_png(), content_type="image/png",
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


async def _ensure_badge_image(badge_svc, tenant_id, badge) -> None:
    """(Re)attach the demo medallion badge image.

    Always refreshes the demo badge art (dev-only, idempotent): this both heals
    a missing S3 object after a LocalStack reset and upgrades older seeds that
    stored a plain placeholder image. The certificate's embedded badge and the
    baked PNG then show the real medallion.
    """
    try:
        await badge_svc.attach_image(
            tenant_id=tenant_id,
            badge_class_id=badge.id,
            content=_badge_png(),
            content_type="image/png",
            actor_id="seed",
        )
        logger.info("Demo seed: (re)attached medallion badge image for %s", badge.id)
    except Exception:
        logger.warning("Demo seed: badge image (re)attach skipped", exc_info=True)


async def _ensure_recipient_photo(db, tenant_id, badge_class_id, settings) -> None:
    """(Re)attach the demo recipient photo for the demo beneficiary's assertion.

    Heals a missing photo S3 object after a LocalStack reset so the certificate
    shows all three images. Dev-only, idempotent.
    """
    from app.services.certificate_service import CertificateService
    from app.services.issuance_service import IssuanceService

    issue_svc = IssuanceService(db=db, settings=settings)
    assertions = await issue_svc.list_assertions_for_class(tenant_id, badge_class_id)
    target = next(
        (a for a in assertions if a.beneficiary_id == _DEMO_BENEFICIARY), None
    )
    if target is None:
        return
    cert_svc = CertificateService(db=db, settings=settings)
    try:
        await cert_svc.upload_recipient_photo(
            tenant_id=tenant_id,
            assertion_id=target.id,
            content=_solid_png((70, 90, 140)),
            content_type="image/png",
            actor_id="seed",
        )
        logger.info("Demo seed: (re)attached recipient photo for %s", target.id)
    except Exception:
        logger.warning("Demo seed: recipient photo (re)attach skipped", exc_info=True)


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
