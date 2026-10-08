"""008 — Certificate template designer (U5).

Adds issuer-designed, tenant-scoped certificate templates and lets a badge class
opt into one:

* ``certificate_templates`` — a new tenant-scoped table holding a saved,
  versioned certificate layout (JSONB) plus optional logo/background S3 keys.
  Standard ``tenant_isolation`` RLS (forced) like the other tenant tables.
* ``badge_classes.custom_template_id`` — nullable FK to a template. When set it
  takes precedence over the built-in ``certificate_template`` string; ON DELETE
  SET NULL reverts affected classes to their built-in template if a template is
  removed.

Chains after 007 (badge analytics). Reversible. The built-in
``certificate_template`` enum/CHECK from 006 is left unchanged — custom
selection is signalled purely by the FK.
"""

from __future__ import annotations

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | None = None
depends_on: str | None = None


def _apply_rls(table: str) -> None:
    """Enable + force RLS and attach the missing_ok tenant_isolation policy.

    Uses ``current_setting('app.tenant_id', true)`` (missing_ok) so an unset
    variable yields NULL rather than erroring, matching migrations 002/005.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS certificate_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            orientation VARCHAR(16) NOT NULL DEFAULT 'portrait',
            layout JSONB NOT NULL DEFAULT '{}'::jsonb,
            logo_s3_key VARCHAR(1024),
            background_s3_key VARCHAR(1024),
            version INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT certificate_templates_orientation_check
              CHECK (orientation IN ('portrait', 'landscape')),
            CONSTRAINT certificate_templates_status_check
              CHECK (status IN ('active', 'archived'))
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_certificate_templates_tenant "
        "ON certificate_templates (tenant_id);"
    )

    _apply_rls("certificate_templates")

    # Badge class opt-in to a custom template (reverts to built-in on delete).
    op.execute(
        "ALTER TABLE badge_classes "
        "ADD COLUMN IF NOT EXISTS custom_template_id UUID "
        "REFERENCES certificate_templates(id) ON DELETE SET NULL;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE badge_classes DROP COLUMN IF EXISTS custom_template_id;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON certificate_templates;")
    op.execute("DROP INDEX IF EXISTS ix_certificate_templates_tenant;")
    op.execute("DROP TABLE IF EXISTS certificate_templates;")
