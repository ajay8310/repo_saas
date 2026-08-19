"""004 — ledger anchoring, consent records, and data-principal requests.

Adds five objects:

``anchor_ledger``
    Append-only hash-chained log backing the 'local' anchor provider.  Not
    tenant-scoped and deliberately *not* under RLS: it is a transparency log
    whose value comes from being globally verifiable, and it holds only Merkle
    roots and hashes — no tenant data and no personal data.  An UPDATE/DELETE
    trigger enforces append-only, mirroring the audit_logs treatment.

``anchor_batches`` / ``document_anchors``
    Tenant-scoped anchoring state and per-credential inclusion proofs.

``consent_records`` / ``erasure_requests``
    Tenant-scoped DPDP records.

Requirements: 10.2, 10.3, 7.5
"""

from __future__ import annotations

from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | None = None
depends_on: str | None = None


def _apply_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
          WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """
    )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # anchor_ledger — global, append-only
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE anchor_ledger (
            seq         BIGINT       PRIMARY KEY,
            prev_hash   VARCHAR(64)  NOT NULL,
            root_hex    VARCHAR(64)  NOT NULL,
            entry_hash  VARCHAR(64)  NOT NULL UNIQUE,
            anchored_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
            batch_id    VARCHAR(64)
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_anchor_ledger_root ON anchor_ledger (root_hex);"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_anchor_ledger_modification()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'anchor_ledger is append-only — UPDATE and DELETE are not '
                'permitted (seq=%)', OLD.seq;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER anchor_ledger_append_only
            BEFORE UPDATE OR DELETE ON anchor_ledger
            FOR EACH ROW
            EXECUTE FUNCTION prevent_anchor_ledger_modification();
        """
    )

    # ------------------------------------------------------------------
    # anchor_batches — tenant-scoped
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE anchor_batches (
            id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id      UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            root_hex       VARCHAR(64) NOT NULL,
            leaf_count     INT         NOT NULL DEFAULT 0,
            status         VARCHAR(32) NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','anchored','failed')),
            provider       VARCHAR(32),
            ledger_ref     VARCHAR(255),
            anchored_at    TIMESTAMPTZ,
            attempt_count  INT         NOT NULL DEFAULT 0,
            failure_reason TEXT,
            receipt        JSONB,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("anchor_batches")
    op.execute(
        "CREATE INDEX ix_anchor_batches_tenant_status "
        "ON anchor_batches (tenant_id, status);"
    )

    # ------------------------------------------------------------------
    # document_anchors — tenant-scoped
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE document_anchors (
            id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id   UUID        NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            document_id UUID        NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            batch_id    UUID        REFERENCES anchor_batches(id) ON DELETE SET NULL,
            leaf_hex    VARCHAR(64) NOT NULL,
            leaf_index  INT,
            proof       JSONB,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (document_id)
        );
        """
    )
    _apply_rls("document_anchors")
    # Partial index: the batching sweep only ever scans unanchored rows.
    op.execute(
        "CREATE INDEX ix_document_anchors_unbatched "
        "ON document_anchors (tenant_id, created_at) WHERE batch_id IS NULL;"
    )

    # ------------------------------------------------------------------
    # consent_records — tenant-scoped, append-only by convention
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE consent_records (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            data_principal_id VARCHAR(512) NOT NULL,
            document_id       UUID         REFERENCES documents(id) ON DELETE CASCADE,
            purpose           VARCHAR(128) NOT NULL,
            legal_basis       VARCHAR(64)  NOT NULL DEFAULT 'consent'
                                  CHECK (legal_basis IN ('consent','legitimate_use',
                                                         'legal_obligation')),
            state             VARCHAR(32)  NOT NULL DEFAULT 'granted'
                                  CHECK (state IN ('granted','withdrawn','expired')),
            scope             JSONB        NOT NULL DEFAULT '[]'::jsonb,
            notice_version    VARCHAR(32)  NOT NULL,
            granted_at        TIMESTAMPTZ,
            withdrawn_at      TIMESTAMPTZ,
            expires_at        TIMESTAMPTZ,
            collected_via     VARCHAR(64),
            evidence          JSONB,
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
        );
        """
    )
    _apply_rls("consent_records")
    # Resolving "is this purpose currently consented?" is the hot path.
    op.execute(
        "CREATE INDEX ix_consent_principal_purpose "
        "ON consent_records (tenant_id, data_principal_id, purpose, created_at DESC);"
    )

    # ------------------------------------------------------------------
    # erasure_requests — tenant-scoped
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE erasure_requests (
            id                UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id         UUID         NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            data_principal_id VARCHAR(512) NOT NULL,
            request_type      VARCHAR(32)  NOT NULL
                                  CHECK (request_type IN ('erasure','correction','access')),
            state             VARCHAR(32)  NOT NULL DEFAULT 'received'
                                  CHECK (state IN ('received','in_progress',
                                                   'completed','rejected')),
            rejection_reason  TEXT,
            details           JSONB,
            outcome           JSONB,
            received_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
            completed_at      TIMESTAMPTZ
        );
        """
    )
    _apply_rls("erasure_requests")
    op.execute(
        "CREATE INDEX ix_erasure_requests_open "
        "ON erasure_requests (tenant_id, state, received_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS erasure_requests CASCADE;")
    op.execute("DROP TABLE IF EXISTS consent_records CASCADE;")
    op.execute("DROP TABLE IF EXISTS document_anchors CASCADE;")
    op.execute("DROP TABLE IF EXISTS anchor_batches CASCADE;")
    op.execute("DROP TRIGGER IF EXISTS anchor_ledger_append_only ON anchor_ledger;")
    op.execute("DROP FUNCTION IF EXISTS prevent_anchor_ledger_modification();")
    op.execute("DROP TABLE IF EXISTS anchor_ledger CASCADE;")
