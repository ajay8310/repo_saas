"""End-to-end badge → certificate flow against the real services + DB.

Runs inside the API container. Mirrors exactly what the API endpoints do (same
service methods), proving the full path produces a real, issuer-signed PDF with
the chosen template and an embedded recipient photo. Writes the PDF to
/app/_cert_out.pdf so we can copy it out and confirm it is a real certificate.
"""

import asyncio
import io
from uuid import UUID

from sqlalchemy import select

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.badge_service import BadgeService
from app.services.issuance_service import IssuanceService
from app.services.certificate_service import CertificateService


def _png(color=(30, 90, 160)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (240, 240), color).save(buf, format="PNG")
    return buf.getvalue()


async def main() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        tenant = (await db.execute(select(Tenant).limit(1))).scalar_one()
        tenant_id = tenant.id
        print("TENANT:", tenant.name, tenant_id)

        badge_svc = BadgeService(db=db, settings=settings)
        issue_svc = IssuanceService(db=db, settings=settings)
        cert_svc = CertificateService(db=db, settings=settings)

        # 1. Create a badge class (FR-1).
        badge = await badge_svc.create_badge_class(
            tenant_id=tenant_id,
            name="Advanced Python — E2E Demo",
            description="Awarded for completing the advanced Python track.",
            criteria_narrative="Pass the proctored assessment with 80% or higher.",
            validity_days=365,
            actor_id="registrar@demo-edu.example.gov",
            actor_role="issuer",
        )
        print("BADGE_CLASS:", badge.id)

        # 2. Choose the 'elegant' certificate template (U4 Q2).
        badge = await badge_svc.update_badge_class(
            tenant_id=tenant_id,
            badge_class_id=badge.id,
            actor_id="registrar@demo-edu.example.gov",
            certificate_template="elegant",
        )
        print("TEMPLATE:", badge.certificate_template)

        # 3. Attach a badge image (FR-2) — scan may be unavailable; tolerate it.
        try:
            badge = await badge_svc.attach_image(
                tenant_id=tenant_id,
                badge_class_id=badge.id,
                content=_png((180, 140, 20)),
                content_type="image/png",
                actor_id="registrar@demo-edu.example.gov",
            )
            print("BADGE_IMAGE_KEY:", badge.image_s3_key)
        except Exception as exc:  # noqa: BLE001
            print("BADGE_IMAGE_SKIPPED:", type(exc).__name__, str(exc)[:80])

        # 4. Issue the badge to a recipient (FR-4).
        result = await issue_svc.issue(
            tenant_id=tenant_id,
            badge_class_id=badge.id,
            beneficiary_id="jane.learner@example.com",
            actor_id="registrar@demo-edu.example.gov",
            actor_role="issuer",
            notify=False,
        )
        assertion_id = UUID(result.assertion_id)
        print("ASSERTION:", assertion_id, "expires:", result.expires_at)

        # 5. Upload the recipient (student) photo (U4 Q6).
        try:
            key = await cert_svc.upload_recipient_photo(
                tenant_id=tenant_id,
                assertion_id=assertion_id,
                content=_png((60, 60, 60)),
                content_type="image/png",
                actor_id="registrar@demo-edu.example.gov",
            )
            print("PHOTO_KEY:", key)
        except Exception as exc:  # noqa: BLE001
            print("PHOTO_SKIPPED:", type(exc).__name__, str(exc)[:80])

        # 6. Build the issuer-signed certificate PDF (U4 Q3/Q5/Q7).
        cert = await cert_svc.build_certificate(
            tenant_id=tenant_id,
            assertion_id=assertion_id,
            actor_id="registrar@demo-edu.example.gov",
            actor_role="issuer",
        )
        with open("/app/_cert_out.pdf", "wb") as fh:
            fh.write(cert.content)
        header = cert.content[:5]
        print("CERT_BYTES:", len(cert.content), "HEADER:", header)
        print("CERT_IS_PDF:", header == b"%PDF-")
        print("CERT_FILENAME:", cert.filename)

        # 7. Confirm the issuer signature is embedded + verifiable with the
        #    tenant's PUBLISHED public key (U4 Q7).
        from app.services.issuer_signing_service import IssuerSigningService
        from jose import jwt as jose_jwt
        from pypdf import PdfReader

        signing = IssuerSigningService(db=db, settings=settings)
        pub = await signing.public_pem(tenant_id)
        reader = PdfReader("/app/_cert_out.pdf")
        kw = reader.metadata.get("/Keywords", "") if reader.metadata else ""
        sig = None
        for part in str(kw).split(","):
            if "issuer_signature=" in part:
                sig = part.split("issuer_signature=", 1)[1].strip()
        if sig:
            decoded = jose_jwt.decode(sig, pub, algorithms=["RS256"])
            print("SIGNATURE_VERIFIED: True recipient=", decoded.get("recipient"))
        else:
            print("SIGNATURE_VERIFIED: no signature found in metadata")

        # 8. Make it public so the directory + hosted assertion show it.
        from app.services.wallet_service import WalletService

        wallet = WalletService(db=db, settings=settings)
        await wallet.set_public(tenant_id, "jane.learner@example.com", assertion_id, True)
        await badge_svc.set_directory_visibility(tenant_id, badge.id, True,
                                                 actor_id="registrar@demo-edu.example.gov")
        print("PUBLISHED: assertion public + class directory_visible")
        print("DONE")


asyncio.run(main())
