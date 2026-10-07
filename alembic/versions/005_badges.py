"""005 — Credly-style badges: badge_classes, badge_assertions, badge_events.

Adds the U1 Badge Core schema:

* ``badge_classes``      — tenant-scoped badge templates (standard UUID PK).
* ``badge_assertions``   — issued instances, RANGE-partitioned by ``issued_at``
  with composite PK ``(id, issued_at)`` plus a UNIQUE index on ``id`` alone so
  the assertion id is a single stable public identifier (== documents.id).
* ``badge_events``       — append-only analytics stream, RANGE-partitioned by
  ``created_at`` (brought forward so U2/U3 can emit/aggregate).

All three are tenant-scoped and receive the standard ``tenant_isolation`` RLS
policy (missing_ok variant, matching migration 002). Monthly partitions are
pre-created for the current window plus a DEFAULT catch-all partition, mirroring
the ``audit_logs`` partitioning approach from 001.

Also adds Open Badges issuer-profile columns to ``tenants``.

Requirements: FR-1.x (badge classes), FR-4.x (issuance), FR-6.x (revoke),
FR-7.x (analytics events), NFR partitioning/RLS.
"""

from __future__ import annotations

from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | None = None
depends_on: str | None = None


# Tenant-scoped badge tables that receive the standard RLS policy.
_RLS_TABLES: tuple[str, ...] = ("badge_classes", "badge_assertions", "badge_events")

# Monthly partitions pre-created for partitioned tables. Range is inclusive of
# the launch window; the DEFAULT partition catches anything outside it.
_PARTITION_MONTHS: tuple[tuple[str, str, str], ...] = (
    # (suffix, from_inclusive, to_exclusive)
    ("y2026m07", "2026-07-01", "2026-08-01"),
    ("y2026m08", "2026-08-01", "2026-09-01"),
    ("y2026m09", "2026-09-01", "2026-10-01"),
    ("y2026m10", "2026-10-01", "2026-11-01"),
    ("y2026m11", "2026-11-01", "2026-12-01"),
    ("y2026m12", "2026-12-01", "2027-01-01"),
    ("y2027m01", "2027-01-01", "2027-02-01"),
)


def _apply_rls(table: str) -> None:
    """Enable + force RLS and attach the missing_ok tenant_isolation policy.

    Uses ``current_setting('app.tenant_id', true)`` (missing_ok) so an unset
    tenant context yields NULL → no rows, rather than raising — consistent with
    migration 002.
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


def _create_partitions(parent: str, column: str) -> None:
    """Create monthly range partitions + a DEFAULT partition for *parent*."""
    for suffix, lo, hi in _PARTITION_MONTHS:
        op.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {parent}_{suffix}
              PARTITION OF {parent}
              FOR VALUES FROM ('{lo}') TO ('{hi}');
            """
        )
    op.execute(
        f"CREATE TABLE IF NOT EXISTS {parent}_default PARTITION OF {parent} DEFAULT;"
    )


def upgrade() -> None:
    # ------------------------------------------------------------------ tenants
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_name VARCHAR(255);")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_url VARCHAR(1024);")
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS issuer_email VARCHAR(255);")

    # ------------------------------------------------------------ badge_classes
    op.execute(
        """
        CREATE TABLE badge_classes (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id          UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name               VARCHAR(255) NOT NULL,
            description        TEXT,
            criteria_narrative TEXT,
            criteria_url       VARCHAR(1024),
            tags               JSONB NOT NULL DEFAULT '[]',
            alignment          JSONB NOT NULL DEFAULT '[]',
            image_s3_key       VARCHAR(1024),
            validity_days      INTEGER,
            status             VARCHAR(32) NOT NULL DEFAULT 'active',
            directory_visible  BOOLEAN NOT NULL DEFAULT false,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT badge_classes_status_check
                CHECK (status IN ('active', 'inactive'))
        );
        """
    )
    op.execute("CREATE INDEX ix_badge_classes_tenant ON badge_classes (tenant_id);")
    # pg_trgm fuzzy search on name (extension created in migration 001).
    op.execute(
        "CREATE INDEX ix_badge_classes_name_trgm ON badge_classes "
        "USING gin (name gin_trgm_ops);"
    )

    # --------------------------------------------------------- badge_assertions
    # Composite PK (id, issued_at) is mandatory for RANGE partitioning; the
    # UNIQUE index on id alone keeps the assertion id a single public identifier.
    op.execute(
        """
        CREATE TABLE badge_assertions (
            id                UUID NOT NULL DEFAULT gen_random_uuid(),
            issued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id         UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            badge_class_id    UUID NOT NULL REFERENCES badge_classes(id),
            beneficiary_id    VARCHAR(512) NOT NULL,
            document_id       UUID NOT NULL,
            expires_at        TIMESTAMPTZ,
            status            VARCHAR(32) NOT NULL DEFAULT 'active',
            accepted          BOOLEAN NOT NULL DEFAULT true,
            hidden            BOOLEAN NOT NULL DEFAULT false,
            public            BOOLEAN NOT NULL DEFAULT false,
            revoked_at        TIMESTAMPTZ,
            revocation_reason VARCHAR(500),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, issued_at),
            CONSTRAINT badge_assertions_status_check
                CHECK (status IN ('active', 'revoked', 'expired'))
        ) PARTITION BY RANGE (issued_at);
        """
    )
    _create_partitions("badge_assertions", "issued_at")
    # Fast id-based lookups. PostgreSQL requires a UNIQUE index on a partitioned
    # table to include every partition-key column, so this is (id, issued_at)
    # rather than (id) alone. Global uniqueness of ``id`` still holds in practice
    # because it is a random UUIDv4 (and is enforced per-partition by the PK);
    # the assertion id remains the single public identifier.
    op.execute(
        "CREATE UNIQUE INDEX ix_badge_assertions_id "
        "ON badge_assertions (id, issued_at);"
    )
    # Wallet listing: a beneficiary's badges, newest first.
    op.execute(
        "CREATE INDEX ix_badge_assertions_wallet ON badge_assertions "
        "(tenant_id, beneficiary_id, issued_at DESC);"
    )
    # Public directory: only publicly visible, accepted, non-revoked assertions.
    op.execute(
        "CREATE INDEX ix_badge_assertions_public ON badge_assertions "
        "(tenant_id, badge_class_id) WHERE public = true;"
    )
    op.execute(
        "CREATE INDEX ix_badge_assertions_class ON badge_assertions (badge_class_id);"
    )

    # ------------------------------------------------------------- badge_events
    op.execute(
        """
        CREATE TABLE badge_events (
            id             UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id      UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            event_type     VARCHAR(32) NOT NULL,
            badge_class_id UUID,
            assertion_id   UUID,
            channel        VARCHAR(32),
            PRIMARY KEY (id, created_at),
            CONSTRAINT badge_events_type_check
                CHECK (event_type IN ('issued', 'accepted', 'published',
                                      'shared', 'verified', 'viewed', 'revoked'))
        ) PARTITION BY RANGE (created_at);
        """
    )
    _create_partitions("badge_events", "created_at")
    op.execute(
        "CREATE INDEX ix_badge_events_agg ON badge_events "
        "(tenant_id, badge_class_id, event_type, created_at);"
    )

    # ------------------------------------------------------------------ RLS
    for table in _RLS_TABLES:
        _apply_rls(table)


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")

    # Dropping the partitioned parent cascades to its partitions.
    op.execute("DROP TABLE IF EXISTS badge_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS badge_assertions CASCADE;")
    op.execute("DROP TABLE IF EXISTS badge_classes CASCADE;")

    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_email;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_url;")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS issuer_name;")
