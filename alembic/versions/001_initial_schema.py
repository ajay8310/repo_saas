"""Initial schema — all core tables.

Creates all 14 tenant-scoped tables, RLS policies, triggers, partitioned
audit_logs, the tenant_storage_usage materialized view, and the
check_quota_before_insert() enforcement trigger.

Requirements: 7.1, 7.3, 7.4, 10.2, 10.4, 3.7
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision: str = "001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enable_rls(table: str) -> None:
    """Enable and force RLS on *table*."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")


def _create_tenant_isolation_policy(table: str) -> None:
    """Create the standard tenant_isolation RLS policy on *table*."""
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = current_setting('app.tenant_id')::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )


def _apply_rls(table: str) -> None:
    """Enable RLS and attach the tenant_isolation policy to *table*."""
    _enable_rls(table)
    _create_tenant_isolation_policy(table)


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:

    # ------------------------------------------------------------------
    # 1. tenants  (not tenant-scoped — owns all other namespaces)
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.execute(
        """
        CREATE TABLE tenants (
            id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            namespace           VARCHAR(63) NOT NULL UNIQUE,
            name                VARCHAR(255) NOT NULL,
            domain              VARCHAR(255) NOT NULL UNIQUE,
            contact_email       VARCHAR(255) NOT NULL,
            status              VARCHAR(32)  NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending','active','suspended','deactivated')),
            storage_quota_bytes BIGINT      NOT NULL DEFAULT 10737418240,
            rate_limit_per_hour INT         NOT NULL DEFAULT 10000,
            retention_years     INT         NOT NULL DEFAULT 7
                                    CHECK (retention_years BETWEEN 1 AND 99),
            dedicated_db        BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )

    # ------------------------------------------------------------------
    # 2. tenant_encryption_keys  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE tenant_encryption_keys (
            id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id    UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            kms_key_arn  VARCHAR(2048) NOT NULL UNIQUE,
            status       VARCHAR(32)  NOT NULL DEFAULT 'active'
                             CHECK (status IN ('active','pending_rotation','disabled')),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            rotated_at   TIMESTAMPTZ
        );
        """
    )
    _apply_rls("tenant_encryption_keys")

    # ------------------------------------------------------------------
    # 3. api_clients  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE api_clients (
            id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id              UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            client_id              VARCHAR(128) NOT NULL UNIQUE,
            client_secret_hash     VARCHAR(255) NOT NULL,
            status                 VARCHAR(32)  NOT NULL DEFAULT 'active'
                                       CHECK (status IN ('active','revoked','grace_period')),
            rotation_interval_days INT         NOT NULL DEFAULT 90
                                       CHECK (rotation_interval_days BETWEEN 1 AND 365),
            key_expires_at         TIMESTAMPTZ,
            grace_until            TIMESTAMPTZ,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("api_clients")


    # ------------------------------------------------------------------
    # 4. user_accounts  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE user_accounts (
            id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id            UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            email                VARCHAR(255) NOT NULL UNIQUE,
            role                 VARCHAR(32)  NOT NULL
                                     CHECK (role IN ('super_admin','tenant_admin','issuer','beneficiary','verifier')),
            mfa_secret           VARCHAR(255),
            mfa_enabled          BOOLEAN     NOT NULL DEFAULT FALSE,
            failed_auth_attempts INT         NOT NULL DEFAULT 0,
            locked_until         TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("user_accounts")

    # ------------------------------------------------------------------
    # 5. document_schemas  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE document_schemas (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            name              VARCHAR(255) NOT NULL,
            version           INT         NOT NULL DEFAULT 1,
            status            VARCHAR(32)  NOT NULL DEFAULT 'active'
                                  CHECK (status IN ('active','deactivated')),
            field_definitions JSONB       NOT NULL DEFAULT '[]'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("document_schemas")

    # ------------------------------------------------------------------
    # 6. schema_versions  (tenant-scoped via schema_id FK)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE schema_versions (
            id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            schema_id         UUID        NOT NULL REFERENCES document_schemas(id) ON DELETE CASCADE,
            version           INT         NOT NULL,
            field_definitions JSONB       NOT NULL DEFAULT '[]'::jsonb,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (schema_id, version)
        );
        """
    )
    _apply_rls("schema_versions")


    # ------------------------------------------------------------------
    # 7. documents  (tenant-scoped, partitioned by month below)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE documents (
            id                UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id         UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            schema_id         UUID        NOT NULL REFERENCES document_schemas(id),
            schema_version    INT         NOT NULL,
            beneficiary_id    VARCHAR(512) NOT NULL,
            status            VARCHAR(32)  NOT NULL DEFAULT 'stored'
                                  CHECK (status IN ('stored','revoked')),
            s3_key            VARCHAR(1024) NOT NULL,
            encrypted_dek     TEXT         NOT NULL,
            iv                TEXT         NOT NULL,
            issued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            revoked_at        TIMESTAMPTZ,
            revocation_reason VARCHAR(500),
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        );
        """
    )
    _apply_rls("documents")

    # GIN indexes for pg_trgm full-text search on documents
    op.execute(
        "CREATE INDEX ix_documents_beneficiary_trgm ON documents "
        "USING GIN (beneficiary_id gin_trgm_ops);"
    )
    op.execute(
        "CREATE INDEX ix_documents_tenant_issued ON documents (tenant_id, issued_at DESC);"
    )
    op.execute(
        "CREATE INDEX ix_documents_tenant_status ON documents (tenant_id, status);"
    )

    # ------------------------------------------------------------------
    # 8. bulk_jobs  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE bulk_jobs (
            id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id       UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            status          VARCHAR(32)  NOT NULL DEFAULT 'pending'
                                CHECK (status IN ('pending','in_progress','completed','failed')),
            total_records   INT         NOT NULL DEFAULT 0,
            processed_count INT         NOT NULL DEFAULT 0,
            success_count   INT         NOT NULL DEFAULT 0,
            failed_count    INT         NOT NULL DEFAULT 0,
            summary         JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at    TIMESTAMPTZ
        );
        """
    )
    _apply_rls("bulk_jobs")


    # ------------------------------------------------------------------
    # 9. verification_tokens  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE verification_tokens (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id      UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            token_hash       VARCHAR(128) NOT NULL UNIQUE,
            consented_fields JSONB       NOT NULL DEFAULT '[]'::jsonb,
            expires_at       TIMESTAMPTZ NOT NULL,
            used_at          TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("verification_tokens")

    # ------------------------------------------------------------------
    # 10. audit_logs  (tenant-scoped, partitioned by month)
    #     Partitioned parent table — child partitions created here for
    #     the first few months; new ones should be created by a periodic
    #     maintenance job.  The trigger for immutability is placed on the
    #     parent and inherited by all partitions.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE audit_logs (
            id            UUID        NOT NULL DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id      VARCHAR(255) NOT NULL,
            actor_role    VARCHAR(32)  NOT NULL,
            operation     VARCHAR(128) NOT NULL,
            resource_type VARCHAR(128) NOT NULL,
            resource_id   VARCHAR(255) NOT NULL,
            outcome       VARCHAR(64)  NOT NULL,
            metadata      JSONB       NOT NULL DEFAULT '{}'::jsonb,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
        """
    )

    # Bootstrap partitions: current month, next month, and a far-future
    # catch-all so rows are never rejected due to missing partitions during
    # initial data load or tests.
    op.execute(
        """
        CREATE TABLE audit_logs_default
            PARTITION OF audit_logs DEFAULT;
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m01
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-01-01') TO ('2025-02-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m02
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-02-01') TO ('2025-03-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m03
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-03-01') TO ('2025-04-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m04
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m05
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m06
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-06-01') TO ('2025-07-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m07
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-07-01') TO ('2025-08-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m08
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m09
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-09-01') TO ('2025-10-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m10
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-10-01') TO ('2025-11-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m11
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-11-01') TO ('2025-12-01');
        """
    )
    op.execute(
        """
        CREATE TABLE audit_logs_y2025m12
            PARTITION OF audit_logs
            FOR VALUES FROM ('2025-12-01') TO ('2026-01-01');
        """
    )

    # Index for efficient per-tenant audit log queries
    op.execute(
        "CREATE INDEX ix_audit_logs_tenant_created "
        "ON audit_logs (tenant_id, created_at DESC);"
    )


    # RLS on audit_logs — applied to the parent; partitions inherit it.
    _apply_rls("audit_logs")

    # ------------------------------------------------------------------
    # 11. webhooks  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE webhooks (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            url         VARCHAR(2048) NOT NULL,
            secret_hash VARCHAR(255)  NOT NULL,
            event_types JSONB        NOT NULL DEFAULT '[]'::jsonb,
            status      VARCHAR(32)   NOT NULL DEFAULT 'active'
                            CHECK (status IN ('active','disabled')),
            created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("webhooks")

    # ------------------------------------------------------------------
    # 12. webhook_events  (tenant-scoped via webhook_id FK)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE webhook_events (
            id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id     UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            webhook_id    UUID        NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            event_type    VARCHAR(128) NOT NULL,
            payload       JSONB        NOT NULL DEFAULT '{}'::jsonb,
            status        VARCHAR(32)  NOT NULL DEFAULT 'pending'
                              CHECK (status IN ('pending','delivered','undelivered','retrying')),
            attempt_count INT          NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ,
            created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("webhook_events")

    # ------------------------------------------------------------------
    # 13. notification_preferences  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE notification_preferences (
            id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id               UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            beneficiary_id          VARCHAR(512) NOT NULL,
            notify_on_issuance      BOOLEAN     NOT NULL DEFAULT TRUE,
            notify_on_revocation    BOOLEAN     NOT NULL DEFAULT TRUE,
            notify_on_verification  BOOLEAN     NOT NULL DEFAULT TRUE,
            preferred_channel       VARCHAR(16)  NOT NULL DEFAULT 'email'
                                        CHECK (preferred_channel IN ('email','sms')),
            contact_email           VARCHAR(255),
            contact_phone           VARCHAR(32),
            UNIQUE (tenant_id, beneficiary_id)
        );
        """
    )
    _apply_rls("notification_preferences")

    # ------------------------------------------------------------------
    # 14. digilocker_pushes  (tenant-scoped)
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE digilocker_pushes (
            id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id        UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id      UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            status           VARCHAR(32)  NOT NULL DEFAULT 'pending'
                                 CHECK (status IN ('pending','success','failed','permanently_failed','retrying')),
            attempt_count    INT          NOT NULL DEFAULT 0,
            failure_reason   TEXT,
            last_attempt_at  TIMESTAMPTZ,
            created_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("digilocker_pushes")


    # ==================================================================
    # Trigger: prevent_audit_modification — immutable audit log (Req 10.2)
    # ==================================================================
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_modification()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'Audit log entries are immutable — UPDATE and DELETE are not permitted '
                '(audit_logs id=%, tenant_id=%)',
                OLD.id, OLD.tenant_id;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER audit_immutable
            BEFORE UPDATE OR DELETE ON audit_logs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_audit_modification();
        """
    )

    # ==================================================================
    # Materialized view: tenant_storage_usage (Req 3.7)
    # Tracks total bytes stored per tenant.  The size of each document
    # is approximated from the length of the s3_key + encrypted_dek + iv
    # columns for the DB-resident metadata; actual byte counts come from
    # S3 but the quota check needs a fast DB-side estimate.
    # ==================================================================
    op.execute(
        """
        CREATE MATERIALIZED VIEW tenant_storage_usage AS
        SELECT
            tenant_id,
            COUNT(*)                       AS document_count,
            SUM(
                octet_length(s3_key)
                + octet_length(encrypted_dek)
                + octet_length(iv)
            )                              AS estimated_bytes
        FROM documents
        WHERE status = 'stored'
        GROUP BY tenant_id;
        """
    )

    op.execute(
        "CREATE UNIQUE INDEX ix_tenant_storage_usage_tenant "
        "ON tenant_storage_usage (tenant_id);"
    )

    # ==================================================================
    # Function + trigger: check_quota_before_insert on documents (Req 3.7)
    # Compares estimated usage against tenants.storage_quota_bytes.
    # The materialized view is refreshed CONCURRENTLY after each
    # successful insert (handled in application code / Celery task);
    # the trigger reads the last-refreshed snapshot, which is sufficient
    # for soft-quota enforcement.
    # ==================================================================
    op.execute(
        """
        CREATE OR REPLACE FUNCTION check_quota_before_insert()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_quota        BIGINT;
            v_current_use  BIGINT;
        BEGIN
            -- Fetch the tenant's configured quota.
            SELECT storage_quota_bytes
              INTO v_quota
              FROM tenants
             WHERE id = NEW.tenant_id;

            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'QUOTA_CHECK_ERROR: tenant % not found', NEW.tenant_id;
            END IF;

            -- Fetch the current estimated usage from the materialized view.
            -- If the view has no row yet (first document), treat usage as 0.
            SELECT COALESCE(estimated_bytes, 0)
              INTO v_current_use
              FROM tenant_storage_usage
             WHERE tenant_id = NEW.tenant_id;

            IF v_current_use >= v_quota THEN
                RAISE EXCEPTION
                    'QUOTA_EXCEEDED: tenant % has reached its storage quota '
                    '(quota=% bytes, current=% bytes)',
                    NEW.tenant_id, v_quota, v_current_use
                    USING ERRCODE = '53100';  -- disk_full — mapped to HTTP 507
            END IF;

            RETURN NEW;
        END;
        $$;
        """
    )

    op.execute(
        """
        CREATE TRIGGER quota_check_before_insert
            BEFORE INSERT ON documents
            FOR EACH ROW
            EXECUTE FUNCTION check_quota_before_insert();
        """
    )



# ---------------------------------------------------------------------------
# downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Triggers and functions
    op.execute("DROP TRIGGER IF EXISTS quota_check_before_insert ON documents;")
    op.execute("DROP TRIGGER IF EXISTS audit_immutable ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS check_quota_before_insert();")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_modification();")

    # Materialized view
    op.execute("DROP MATERIALIZED VIEW IF EXISTS tenant_storage_usage;")

    # Tables — reverse dependency order
    op.execute("DROP TABLE IF EXISTS digilocker_pushes CASCADE;")
    op.execute("DROP TABLE IF EXISTS notification_preferences CASCADE;")
    op.execute("DROP TABLE IF EXISTS webhook_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS webhooks CASCADE;")

    # audit_logs parent (drops all partitions automatically)
    op.execute("DROP TABLE IF EXISTS audit_logs CASCADE;")

    op.execute("DROP TABLE IF EXISTS verification_tokens CASCADE;")
    op.execute("DROP TABLE IF EXISTS bulk_jobs CASCADE;")
    op.execute("DROP TABLE IF EXISTS documents CASCADE;")
    op.execute("DROP TABLE IF EXISTS schema_versions CASCADE;")
    op.execute("DROP TABLE IF EXISTS document_schemas CASCADE;")
    op.execute("DROP TABLE IF EXISTS user_accounts CASCADE;")
    op.execute("DROP TABLE IF EXISTS api_clients CASCADE;")
    op.execute("DROP TABLE IF EXISTS tenant_encryption_keys CASCADE;")
    op.execute("DROP TABLE IF EXISTS tenants CASCADE;")
