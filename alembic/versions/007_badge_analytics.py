"""007 — Badge analytics daily rollup (U3).

Creates ``badge_analytics_daily``: a per-(tenant, day, badge_class) rollup over
``badge_events`` that the analytics dashboard reads. A row with
``badge_class_id IS NULL`` is the tenant-wide total for the day.

Tenant-scoped → RLS enabled/forced with the standard ``tenant_isolation`` policy
(missing_ok variant, matching 002/005). UNIQUE(tenant_id, day, badge_class_id)
is the idempotent upsert key for the aggregator.

NULLs don't participate in a plain UNIQUE constraint, so tenant-wide rows
(badge_class_id IS NULL) are de-duplicated with a partial unique index instead;
the per-class rows use a normal unique index. Together they guarantee one row
per logical key for both cases.

Reversible.
"""

from __future__ import annotations

from alembic import op

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE badge_analytics_daily (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            day                TIMESTAMPTZ NOT NULL,
            badge_class_id     UUID,
            issued_count       INTEGER NOT NULL DEFAULT 0,
            accepted_count     INTEGER NOT NULL DEFAULT 0,
            published_count    INTEGER NOT NULL DEFAULT 0,
            shared_count       INTEGER NOT NULL DEFAULT 0,
            verified_count     INTEGER NOT NULL DEFAULT 0,
            viewed_count       INTEGER NOT NULL DEFAULT 0,
            channel_breakdown  JSONB NOT NULL DEFAULT '{}',
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    # Per-class rows: one per (tenant, day, class).
    op.execute(
        """
        CREATE UNIQUE INDEX ux_badge_analytics_class
          ON badge_analytics_daily (tenant_id, day, badge_class_id)
          WHERE badge_class_id IS NOT NULL;
        """
    )
    # Tenant-wide rows (class is NULL): one per (tenant, day).
    op.execute(
        """
        CREATE UNIQUE INDEX ux_badge_analytics_tenantwide
          ON badge_analytics_daily (tenant_id, day)
          WHERE badge_class_id IS NULL;
        """
    )
    op.execute(
        "CREATE INDEX ix_badge_analytics_tenant_day "
        "ON badge_analytics_daily (tenant_id, day);"
    )

    # RLS (missing_ok variant, matching 002/005).
    op.execute("ALTER TABLE badge_analytics_daily ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE badge_analytics_daily FORCE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON badge_analytics_daily;")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON badge_analytics_daily
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON badge_analytics_daily;")
    op.execute("DROP TABLE IF EXISTS badge_analytics_daily CASCADE;")
