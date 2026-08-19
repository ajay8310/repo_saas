"""003 — store webhook signing secrets sealed so signatures are reproducible.

001 stored only ``webhooks.secret_hash`` (SHA-256 of the secret) and
``WebhookService.deliver_event`` then computed the HMAC *over that hash*.
A receiver holds the secret, not its hash, so it could never reproduce the
signature — every ``X-Webhook-Signature`` header was unverifiable.

Signing requires the original secret, so it has to be recoverable rather than
hashed.  ``secret_sealed`` holds it as a vault envelope (AES-256-GCM, tenant id
bound as AAD).  ``secret_hash`` is retained as a non-reversible fingerprint for
equality checks and audit, but is no longer used for signing.

Rows created before this migration have no sealed secret and cannot be signed
correctly; delivery for them fails with a clear reason rather than emitting a
bogus signature.  Operators re-register those webhooks to get a signable secret.

Requirements: 8.7, 8.8
"""

from __future__ import annotations

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE webhooks ADD COLUMN IF NOT EXISTS secret_sealed TEXT;")
    op.execute(
        """
        COMMENT ON COLUMN webhooks.secret_sealed IS
          'Vault envelope (v1:<provider>:<key_id>:<nonce>:<ct>) holding the '
          'HMAC signing secret. Required to produce X-Webhook-Signature.';
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE webhooks DROP COLUMN IF EXISTS secret_sealed;")
