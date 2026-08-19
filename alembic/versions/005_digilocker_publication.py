"""005 — record what was actually published to DigiLocker.

001 tracked only status, attempt count, and failure reason, which is enough to
say "we tried" but not enough to say "the citizen has it". Four columns are
added so a publication is evidenced rather than asserted:

``doctype``
    The DigiLocker document type used, pinned per push so a later change to
    ``digilocker_default_doctype`` cannot retroactively rewrite history.

``digilocker_uri``
    The locker reference DigiLocker returns. The connector treats a 2xx with no
    URI as a failure, because a success we cannot point at is not a success.

``published_at``
    Distinct from ``last_attempt_at``: the moment it landed, not the moment we
    last tried.

``delivery_mode``
    'sandbox' or 'live'. The connector can simulate publication so the workflow
    is usable before an authority's credentials are provisioned; this column is
    what stops a simulated push being audited as a real one.

Also adds a partial index for the retry sweep, which only ever scans
non-terminal rows.

Requirements: 12.1, 12.4, 12.5
"""

from __future__ import annotations

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE digilocker_pushes
            ADD COLUMN IF NOT EXISTS doctype        VARCHAR(64),
            ADD COLUMN IF NOT EXISTS digilocker_uri VARCHAR(512),
            ADD COLUMN IF NOT EXISTS published_at   TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS delivery_mode  VARCHAR(16);
        """
    )
    op.execute(
        """
        ALTER TABLE digilocker_pushes
            DROP CONSTRAINT IF EXISTS digilocker_pushes_delivery_mode_check;
        """
    )
    op.execute(
        """
        ALTER TABLE digilocker_pushes
            ADD CONSTRAINT digilocker_pushes_delivery_mode_check
            CHECK (delivery_mode IS NULL OR delivery_mode IN ('sandbox','live'));
        """
    )

    # The sweep looks up pending/retrying rows per tenant; a partial index keeps
    # it off the successful majority.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_digilocker_pushes_outstanding
            ON digilocker_pushes (tenant_id, last_attempt_at)
            WHERE status IN ('pending','retrying');
        """
    )
    # One lookup per credential drives the issuer UI.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_digilocker_pushes_document
            ON digilocker_pushes (document_id, created_at DESC);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_digilocker_pushes_document;")
    op.execute("DROP INDEX IF EXISTS ix_digilocker_pushes_outstanding;")
    op.execute(
        "ALTER TABLE digilocker_pushes "
        "DROP CONSTRAINT IF EXISTS digilocker_pushes_delivery_mode_check;"
    )
    op.execute(
        """
        ALTER TABLE digilocker_pushes
            DROP COLUMN IF EXISTS delivery_mode,
            DROP COLUMN IF EXISTS published_at,
            DROP COLUMN IF EXISTS digilocker_uri,
            DROP COLUMN IF EXISTS doctype;
        """
    )
