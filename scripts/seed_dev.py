"""
Seed a local development tenant so the API is actually usable.

``bootstrap_demo.py`` only writes a ``.env`` with a JWT keypair. Nothing can
authenticate against that: ``POST /auth/token`` validates a ``client_id`` against
``api_clients``, and that table starts empty. This script creates the minimum set
of rows needed to sign in and issue a credential end to end:

  - one active tenant
  - one API client with a known secret (bcrypt hashed, as the service expects)
  - user accounts for the beneficiary OTP flow and the admin MFA flow
  - one active document schema to issue against
  - a tenant encryption key row pointing at a real LocalStack KMS key
  - the S3 bucket uploads write to

Two details that matter and are easy to get wrong:

*RLS.* ``api_clients``, ``user_accounts`` and ``tenant_encryption_keys`` all have
FORCE row-level security with a ``WITH CHECK`` on ``app.tenant_id``. Inserts fail
unless the GUC is set in the *same transaction*, which is why every insert below
is preceded by ``set_config(..., true)``.

*KMS.* ``tenant_service`` currently provisions a placeholder ARN
(``...:000000000000:key/<uuid>``) that no KMS will accept. This script creates a
real key in LocalStack and stores that ARN instead, so encryption works.

Idempotent: re-running reports what already exists rather than duplicating.

Usage:
    python scripts/seed_dev.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Values are intentionally fixed and obvious so they can be pasted into the
# login form. They are development-only.
TENANT_NAMESPACE = "demo_university"
TENANT_NAME = "Demo State University"
TENANT_DOMAIN = "demo-university.gov.in"
TENANT_CONTACT = "registrar@demo-university.gov.in"

CLIENT_ID = "demo_university_local"
CLIENT_SECRET = "local-dev-secret-change-me"

BENEFICIARY_EMAIL = "student@demo-university.gov.in"
ADMIN_EMAIL = "admin@demo-university.gov.in"

SCHEMA_NAME = "Degree Certificate"
SCHEMA_FIELDS = [
    {"name": "student_name", "type": "string", "required": True},
    {"name": "degree", "type": "string", "required": True},
    {"name": "graduation_year", "type": "integer", "required": True},
    {"name": "grade", "type": "string", "required": False},
]


def provision_aws() -> str:
    """Create the S3 bucket and a KMS key in LocalStack. Returns the key ARN."""
    import boto3
    from botocore.exceptions import ClientError

    from app.config import get_settings

    settings = get_settings()
    common = {
        "region_name": settings.aws_region,
        # LocalStack accepts any credentials but boto3 requires some.
        "aws_access_key_id": settings.aws_access_key_id or "test",
        "aws_secret_access_key": settings.aws_secret_access_key or "test",
    }

    s3 = boto3.client("s3", endpoint_url=settings.s3_endpoint_url or None, **common)
    bucket = settings.s3_bucket_name
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"  s3 bucket           : {bucket} (exists)")
    except ClientError:
        # ap-south-1 and every other non-us-east-1 region require the location
        # constraint; us-east-1 rejects it.
        kwargs = {"Bucket": bucket}
        if settings.aws_region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": settings.aws_region
            }
        s3.create_bucket(**kwargs)
        print(f"  s3 bucket           : {bucket} (created)")

    kms = boto3.client("kms", endpoint_url=settings.kms_endpoint_url or None, **common)
    alias = f"alias/{TENANT_NAMESPACE}-cmk"

    try:
        described = kms.describe_key(KeyId=alias)
        arn = described["KeyMetadata"]["Arn"]
        print(f"  kms key             : {alias} (exists)")
        return arn
    except ClientError:
        pass

    created = kms.create_key(
        Description=f"Dev CMK for {TENANT_NAMESPACE}",
        KeyUsage="ENCRYPT_DECRYPT",
        KeySpec="SYMMETRIC_DEFAULT",
    )
    arn = created["KeyMetadata"]["Arn"]
    kms.create_alias(AliasName=alias, TargetKeyId=created["KeyMetadata"]["KeyId"])
    print(f"  kms key             : {alias} (created)")
    return arn


async def seed(kms_arn: str) -> None:
    """Insert the tenant and its dependent rows."""
    from sqlalchemy import select, text
    from passlib.context import CryptContext

    from app.db.session import AsyncSessionLocal
    from app.models.schema import DocumentSchema
    from app.models.tenant import ApiClient, Tenant, TenantEncryptionKey
    from app.models.user import UserAccount

    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async with AsyncSessionLocal() as db:
        # --- tenant (not RLS-scoped; it is the root of every other scope) ---
        tenant = (
            await db.execute(select(Tenant).where(Tenant.namespace == TENANT_NAMESPACE))
        ).scalar_one_or_none()

        if tenant is None:
            tenant = Tenant(
                namespace=TENANT_NAMESPACE,
                name=TENANT_NAME,
                domain=TENANT_DOMAIN,
                contact_email=TENANT_CONTACT,
                # Active, not pending: a pending tenant cannot authenticate.
                status="active",
            )
            db.add(tenant)
            await db.commit()
            await db.refresh(tenant)
            print(f"  tenant              : {TENANT_NAMESPACE} (created)")
        else:
            if tenant.status != "active":
                tenant.status = "active"
                await db.commit()
            print(f"  tenant              : {TENANT_NAMESPACE} (exists)")

        tid = str(tenant.id)

        # Everything below is RLS-protected. set_config with is_local=true scopes
        # the GUC to this transaction, so it must be re-issued after each commit.
        async def with_tenant() -> None:
            await db.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid}
            )

        # --- encryption key ---
        await with_tenant()
        existing_key = (
            await db.execute(
                select(TenantEncryptionKey).where(
                    TenantEncryptionKey.tenant_id == tenant.id
                )
            )
        ).scalar_one_or_none()

        if existing_key is None:
            db.add(
                TenantEncryptionKey(
                    tenant_id=tenant.id, kms_key_arn=kms_arn, status="active"
                )
            )
            await db.commit()
            print("  encryption key      : created")
        else:
            if existing_key.kms_key_arn != kms_arn:
                existing_key.kms_key_arn = kms_arn
                await db.commit()
                print("  encryption key      : updated to real KMS ARN")
            else:
                print("  encryption key      : exists")

        # --- api client ---
        await with_tenant()
        client = (
            await db.execute(select(ApiClient).where(ApiClient.client_id == CLIENT_ID))
        ).scalar_one_or_none()

        if client is None:
            db.add(
                ApiClient(
                    tenant_id=tenant.id,
                    client_id=CLIENT_ID,
                    client_secret_hash=pwd.hash(CLIENT_SECRET),
                    status="active",
                )
            )
            await db.commit()
            print(f"  api client          : {CLIENT_ID} (created)")
        else:
            print(f"  api client          : {CLIENT_ID} (exists)")

        # --- user accounts ---
        for email, role in ((BENEFICIARY_EMAIL, "beneficiary"), (ADMIN_EMAIL, "tenant_admin")):
            await with_tenant()
            user = (
                await db.execute(select(UserAccount).where(UserAccount.email == email))
            ).scalar_one_or_none()
            if user is None:
                db.add(
                    UserAccount(
                        tenant_id=tenant.id,
                        email=email,
                        role=role,
                        mfa_enabled=False,
                    )
                )
                await db.commit()
                print(f"  user                : {email} ({role}, created)")
            else:
                print(f"  user                : {email} ({role}, exists)")

        # --- schema ---
        await with_tenant()
        schema = (
            await db.execute(
                select(DocumentSchema).where(DocumentSchema.name == SCHEMA_NAME)
            )
        ).scalar_one_or_none()

        if schema is None:
            db.add(
                DocumentSchema(
                    tenant_id=tenant.id,
                    name=SCHEMA_NAME,
                    version=1,
                    status="active",
                    field_definitions=SCHEMA_FIELDS,
                )
            )
            await db.commit()
            print(f"  schema              : {SCHEMA_NAME} (created)")
        else:
            print(f"  schema              : {SCHEMA_NAME} (exists)")

        print()
        print("  Sign in with:")
        print(f"    client_id     = {CLIENT_ID}")
        print(f"    client_secret = {CLIENT_SECRET}")
        print(f"    tenant_id     = {tid}")
        print(f"    cmk_arn       = {kms_arn}")


def main() -> int:
    # Fail early with a clear message rather than a driver traceback.
    if not os.environ.get("DATABASE_URL") and not (ROOT / ".env").exists():
        print("ERROR: no .env found. Run: python scripts/bootstrap_demo.py")
        return 1

    print("Seeding local development data...")
    try:
        kms_arn = provision_aws()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not provision S3/KMS via LocalStack: {exc}")
        print("       Is LocalStack running? docker compose up -d localstack")
        return 1

    try:
        asyncio.run(seed(kms_arn))
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: seeding failed: {exc}")
        print("       Are Postgres up and migrations applied? alembic upgrade head")
        return 1

    print("\nOK: seed complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
