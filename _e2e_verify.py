"""Verify the issuer signature on the already-generated certificate, without pypdf.

Reads the PDF's /Keywords via a minimal parse, extracts issuer_signature, and
verifies it against the tenant's PUBLISHED public key (U4 Q7).
"""

import asyncio
import re

from jose import jwt as jose_jwt
from sqlalchemy import select

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant
from app.services.issuer_signing_service import IssuerSigningService


async def main() -> None:
    settings = get_settings()
    data = open("/app/_cert_out.pdf", "rb").read()
    # PDF Keywords are stored as plain text in the metadata dictionary; find the
    # issuer_signature=... token (a compact JWS: three base64url parts).
    text = data.decode("latin-1", errors="ignore")
    m = re.search(r"issuer_signature=([A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+)", text)
    if not m:
        print("NO_SIGNATURE_FOUND")
        return
    sig = m.group(1)

    async with AsyncSessionLocal() as db:
        tenant = (await db.execute(select(Tenant).limit(1))).scalar_one()
        signing = IssuerSigningService(db=db, settings=settings)
        pub = await signing.public_pem(tenant.id)
        key_id = tenant.issuer_key_id

    decoded = jose_jwt.decode(sig, pub, algorithms=["RS256"])
    print("SIGNATURE_VERIFIED: True")
    print("ISSUER_KEY_ID:", key_id)
    print("SIGNED_CLAIMS:", decoded)


asyncio.run(main())
