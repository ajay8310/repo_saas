"""009 — Bring-your-own certificate PDF (tenant-supplied signed certificates).

Lets a tenant upload a pre-built certificate PDF (its own design) and have the
platform digitally sign (RS256 JWS over the PDF's SHA-256, with the tenant's
existing issuer key) and issue it to a beneficiary — no template rendering.

Adds three nullable columns to ``badge_assertions`` (parent ALTER cascades to
every partition automatically; the table already has RLS from 005):

* ``certificate_pdf_s3_key``        — S3 key of the stored, SSE-KMS-encrypted PDF.
* ``certificate_pdf_sha256``        — hex SHA-256 of the uploaded PDF bytes (what was signed).
* ``certificate_pdf_signature_jws`` — the issuer's RS256 JWS over the signing payload.

When ``certificate_pdf_s3_key`` is set, certificate download returns this stored
PDF instead of rendering a template. Reversible.
"""

from __future__ import annotations

from alembic import op

revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE badge_assertions "
        "ADD COLUMN IF NOT EXISTS certificate_pdf_s3_key VARCHAR(1024);"
    )
    op.execute(
        "ALTER TABLE badge_assertions "
        "ADD COLUMN IF NOT EXISTS certificate_pdf_sha256 VARCHAR(64);"
    )
    op.execute(
        "ALTER TABLE badge_assertions "
        "ADD COLUMN IF NOT EXISTS certificate_pdf_signature_jws TEXT;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE badge_assertions DROP COLUMN IF EXISTS certificate_pdf_signature_jws;")
    op.execute("ALTER TABLE badge_assertions DROP COLUMN IF EXISTS certificate_pdf_sha256;")
    op.execute("ALTER TABLE badge_assertions DROP COLUMN IF EXISTS certificate_pdf_s3_key;")
