"""010 — Issuer X.509 signing certificate for embedded PAdES PDF signatures.

Adds ``tenants.issuer_signing_cert`` (PEM): a self-signed X.509 certificate
derived from the tenant's existing RSA issuer keypair (from migration 006). It
is used by pyHanko to embed a true PAdES signature inside a tenant-supplied
certificate PDF, so the signed PDF validates in Adobe/any PDF verifier.

``tenants`` is the root entity (not RLS-scoped), so this only adds a column.
Reversible.
"""

from __future__ import annotations

from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_signing_cert TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_signing_cert;")
