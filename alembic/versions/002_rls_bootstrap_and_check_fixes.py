"""002 — make RLS tolerant of unset context, fix CHECK constraints.

Three defects in 001 are addressed here.

1. The ``tenant_isolation`` policies call ``current_setting('app.tenant_id')``
   with no ``missing_ok`` argument.  That *raises* when the GUC was never set,
   so any code path touching an RLS table before ``set_tenant_context`` fails
   hard rather than simply seeing no rows.  Switching to
   ``current_setting('app.tenant_id', true)`` yields NULL instead, and the
   ``tenant_id = NULL`` comparison is never true — so an unset context now
   means "no access" rather than "500".

2. Authentication cannot set a tenant context because resolving the tenant is
   the *result* of authentication, not an input to it.  Two narrowly scoped
   bootstrap policies permit SELECT on the credential tables only while no
   tenant context is set.  See the comment on ``_add_bootstrap_policy`` for
   why this is limited to these two tables.

3. ``bulk_jobs.status`` rejects ``completed_with_errors``, which
   ``app/tasks/bulk_upload.py`` writes on any partially failed job, so every
   partial batch died on a CheckViolation.

Requirements: 7.1, 7.3, 13.6
"""

from __future__ import annotations

from alembic import op

revision: str = "002"
down_revision: str | None = "001"
branch_labels: str | None = None
depends_on: str | None = None


# Every table 001 attached a tenant_isolation policy to.
_RLS_TABLES: tuple[str, ...] = (
    "tenant_encryption_keys",
    "api_clients",
    "user_accounts",
    "document_schemas",
    "schema_versions",
    "documents",
    "bulk_jobs",
    "verification_tokens",
    "audit_logs",
    "webhooks",
    "webhook_events",
    "notification_preferences",
    "digilocker_pushes",
)

# Tables authentication must read before any tenant is known.  Both hold only
# credential material (bcrypt hashes, TOTP secrets) and tenant linkage — not
# document contents or beneficiary PII.
_BOOTSTRAP_TABLES: tuple[str, ...] = ("api_clients", "user_accounts")


def _replace_isolation_policy(table: str, *, missing_ok: bool) -> None:
    """Recreate ``tenant_isolation`` on *table* with or without ``missing_ok``."""
    setting = (
        "current_setting('app.tenant_id', true)"
        if missing_ok
        else "current_setting('app.tenant_id')"
    )
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
          USING (tenant_id = {setting}::uuid)
          WITH CHECK (tenant_id = {setting}::uuid);
        """
    )


def _add_bootstrap_policy(table: str) -> None:
    """Permit SELECT on *table* only while ``app.tenant_id`` is unset.

    RLS policies are permissive and OR'd together, so this widens SELECT for
    exactly one situation: a session that has not yet established a tenant.
    Authentication is the only such path — ``authenticate_client`` looks up a
    globally unique ``client_id`` and ``send_otp``/``verify_otp`` look up an
    email plus tenant namespace, all before a tenant id exists.

    Deliberately SELECT-only, and deliberately not applied to ``documents``,
    ``verification_tokens``, ``audit_logs`` or anything else holding subject
    data: those keep the strict policy, so a code path that forgets
    ``set_tenant_context`` sees zero rows rather than another tenant's data.
    """
    op.execute(f"DROP POLICY IF EXISTS auth_bootstrap ON {table};")
    op.execute(
        f"""
        CREATE POLICY auth_bootstrap ON {table}
          FOR SELECT
          USING (current_setting('app.tenant_id', true) IS NULL
                 OR current_setting('app.tenant_id', true) = '');
        """
    )


def upgrade() -> None:
    # 1. Unset tenant context must mean "no rows", not an exception.
    for table in _RLS_TABLES:
        _replace_isolation_policy(table, missing_ok=True)

    # 2. Let authentication read credential tables pre-tenant.
    for table in _BOOTSTRAP_TABLES:
        _add_bootstrap_policy(table)

    # 3. bulk_jobs.status must accept the value the worker actually writes.
    op.execute("ALTER TABLE bulk_jobs DROP CONSTRAINT IF EXISTS bulk_jobs_status_check;")
    op.execute(
        """
        ALTER TABLE bulk_jobs
          ADD CONSTRAINT bulk_jobs_status_check
          CHECK (status IN ('pending','in_progress','completed',
                            'completed_with_errors','failed'));
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bulk_jobs DROP CONSTRAINT IF EXISTS bulk_jobs_status_check;")
    op.execute(
        """
        ALTER TABLE bulk_jobs
          ADD CONSTRAINT bulk_jobs_status_check
          CHECK (status IN ('pending','in_progress','completed','failed'));
        """
    )

    for table in _BOOTSTRAP_TABLES:
        op.execute(f"DROP POLICY IF EXISTS auth_bootstrap ON {table};")

    for table in _RLS_TABLES:
        _replace_isolation_policy(table, missing_ok=False)
