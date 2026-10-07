"""006 — Certificates & issuer signing (U4).

Adds the schema for downloadable, issuer-signed certificates:

* ``badge_classes.certificate_template`` — which built-in template renders this
  class's certificates (classic | modern | elegant | minimal).
* ``badge_assertions.recipient_photo_s3_key`` — the recipient (student) photo
  shown on the certificate and, when the assertion is public, on the hosted
  verification page.
* ``tenants`` issuer signing columns — a per-tenant RS256 keypair so each
  issuer's certificates carry their own signature; the public key is published
  for verification.

All target tables already exist with RLS (tenants is the root entity; the badge
tables got RLS in 005), so this migration only adds columns. The badge_assertions
ALTER propagates to every partition automatically.

Reversible.
"""

from __future__ import annotations

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Certificate template per badge class.
    op.execute(
        "ALTER TABLE badge_classes "
        "ADD COLUMN IF NOT EXISTS certificate_template VARCHAR(32) "
        "NOT NULL DEFAULT 'classic';"
    )
    op.execute(
        """
        ALTER TABLE badge_classes
          ADD CONSTRAINT badge_classes_certificate_template_check
          CHECK (certificate_template IN ('classic', 'modern', 'elegant', 'minimal'));
        """
    )

    # Recipient photo per assertion (parent ALTER cascades to partitions).
    op.execute(
        "ALTER TABLE badge_assertions "
        "ADD COLUMN IF NOT EXISTS recipient_photo_s3_key VARCHAR(1024);"
    )

    # Per-tenant issuer signing keypair.
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_signing_public_key TEXT;"
    )
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_signing_private_key TEXT;"
    )
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_key_id VARCHAR(64);")
    op.execute(
        "ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_key_generated_at TIMESTAMPTZ;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_key_generated_at;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_key_id;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_signing_private_key;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_signing_public_key;")

    op.execute("ALTER TABLE badge_assertions DROP COLUMN IF EXISTS recipient_photo_s3_key;")

    op.execute(
        "ALTER TABLE badge_classes "
        "DROP CONSTRAINT IF EXISTS badge_classes_certificate_template_check;"
    )
    op.execute("ALTER TABLE badge_classes DROP COLUMN IF EXISTS certificate_template;")
