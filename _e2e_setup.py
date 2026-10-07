"""One-off E2E helper: ensure a tenant exists and mint a valid issuer JWT.

Run inside the API container. Prints a tenant_id and a signed RS256 token the
real API will accept, so we can drive the badge → certificate flow for real.
"""

import asyncio
import time
from uuid import uuid4

from jose import jwt
from sqlalchemy import select, text

from app.config import get_settings
from app.db.session import AsyncSessionLocal
from app.models.tenant import Tenant


async def main() -> None:
    settings = get_settings()
    async with AsyncSessionLocal() as db:
        # Reuse an existing active tenant if present, else create one.
        existing = (await db.execute(select(Tenant).limit(1))).scalar_one_or_none()
        if existing is None:
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
        else:
            tenant = existing
            # Make sure it's active and has an issuer profile for nice certs.
            tenant.status = "active"
            if not tenant.issuer_name:
                tenant.issuer_name = tenant.name
            await db.commit()

        tenant_id = str(tenant.id)

    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "registrar@demo-edu.example.gov",
            "tenant_id": tenant_id,
            "roles": ["tenant_admin", "issuer"],
            "iat": now,
            "exp": now + 3600,
        },
        settings.jwt_private_key,
        algorithm=settings.jwt_algorithm,
    )
    print("TENANT_ID=" + tenant_id)
    print("TOKEN=" + token)


asyncio.run(main())
