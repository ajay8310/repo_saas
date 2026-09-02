# API Documentation

All versioned endpoints are under `/api/v1` (configurable via `settings.api_v1_prefix`). Health at `/health`. OpenAPI at `/api/v1/openapi.json`, Swagger at `/api/v1/docs`, ReDoc at `/api/v1/redoc`. Auth is RS256 JWT (Bearer). RBAC via `require_permission`.

## REST APIs (by router)

### Auth (`app/routers/auth.py`)
- **POST** `/api/v1/auth/token` — OAuth2 client-credentials → JWT.
- **POST** `/api/v1/auth/otp/request` — request beneficiary OTP.
- **POST** `/api/v1/auth/otp/verify` — verify OTP → JWT.
- **POST** `/api/v1/auth/mfa/challenge` — begin admin TOTP challenge.
- **POST** `/api/v1/auth/mfa/verify` — verify TOTP → JWT.

### Tenants (`app/routers/tenants.py`) — Super Admin
- **POST** `/api/v1/admin/tenants` — create (pending).
- **GET** `/api/v1/admin/tenants/{id}` — read.
- **PATCH** `/api/v1/admin/tenants/{id}` — update quota/rate-limit/categories.
- **POST** `/api/v1/admin/tenants/{id}/approve|suspend|deactivate` — lifecycle transitions.
- **POST** `/api/v1/admin/tenants/{id}/rotate-key` — rotate API key (grace period).

### Schemas (`app/routers/schemas.py`)
- **POST** `/api/v1/schemas` — create.
- **GET** `/api/v1/schemas/{id}` — read.
- **PATCH** `/api/v1/schemas/{id}` — update (breaking-change detection).
- **DELETE** `/api/v1/schemas/{id}` — deactivate.
- **GET** `/api/v1/schemas/{id}/versions` — version history.
- **GET** `/api/v1/schemas/{id}/export` — JSON export.

### Documents (`app/routers/documents.py`)
- **POST** `/api/v1/documents` — single upload/issue.
- **POST** `/api/v1/documents/bulk` — bulk upload (async job).
- **GET** `/api/v1/documents/bulk/{job_id}` — bulk job status.
- **GET** `/api/v1/documents` — list/search (paginated, RLS-scoped).
- **GET** `/api/v1/documents/{id}` — retrieve metadata.
- **GET** `/api/v1/documents/{id}/download` — signed PDF / JSON-LD + QR.
- **POST** `/api/v1/documents/{id}/revoke` — revoke with reason.
- **POST** `/api/v1/documents/bulk-revoke` — bulk revoke (per-item results).

### Verification (`app/routers/verification.py`)
- **POST** `/api/v1/verifications/tokens` — generate consent-scoped token.
- **GET** `/api/v1/verifications/{token}` — consume token (single-use).
- **GET** `/api/v1/verify/{credential_id}` — public validity status.
- **GET** `/api/v1/verify/qr/{token}` — public HTML verification page.

### Anchoring (`app/routers/anchoring.py`)
- Endpoints to query anchor status / inclusion proof for a credential (batch Merkle root).

### Webhooks (`app/routers/webhooks.py`)
- **POST/GET/DELETE** `/api/v1/webhooks` — register/list/delete tenant webhooks; delivery is HMAC-signed.

### Notifications (`app/routers/notifications.py`)
- **GET/PATCH** `/api/v1/beneficiaries/me/notification-preferences` — read/update preferences.

### Privacy (`app/routers/privacy.py`)
- Consent capture and data-principal rights (erasure request) endpoints (DPDP-aligned).

### Search (`app/routers/search.py`)
- **GET** `/api/v1/documents?q=...&filters` — faceted, sorted, paginated search (also surfaced via documents router).

### Audit (`app/routers/audit.py`)
- **GET** `/api/v1/audit-logs` — tenant-scoped query.
- **GET** `/api/v1/audit-logs/export?format=json|csv` — export.

## Internal APIs (service layer, representative)
- `DocumentService.upload_document(tenant_id, schema_id, beneficiary_id, content: bytes, cmk_arn, actor_id, actor_role) -> UploadResult{credential_id, status}`
- `DocumentService.get_document(...) -> Document | None`; `download_document(...) -> RenderedDocument`; `revoke_document(...) -> Document`; `bulk_revoke(...)`.
- `SchemaService.create_schema/update_schema/deactivate_schema/export_schema`; `_validate_field_definitions`.
- `VerificationService.generate_token(...)`, `consume_token(raw) -> VerificationResult`, `verify_credential_public(credential_id) -> {status}`.
- `AuthService.authenticate_client / send_otp / verify_otp / initiate_mfa / verify_mfa`.
- `SearchService.search(tenant_id, SearchParams) -> {items,total,page,page_size}`.
- `AnchoringService.record_document(...)`, provider `publish(root_hex, batch_id)`.

## Data Models (SQLAlchemy, `app/models/`)
- **Tenant / TenantEncryptionKey / ApiClient** — org, KMS key ARN, client credentials (bcrypt hash, status: active|grace_period|revoked).
- **UserAccount** — roles, MFA secret, failed-attempt counters, lockout.
- **DocumentSchema / SchemaVersion** — field_definitions (JSONB), monotonic version.
- **Document / BulkJob** — credential metadata (status stored|revoked, s3_key, encrypted_dek, iv), bulk job status.
- **VerificationToken** — SHA-256 token hash, consented_fields, expires_at, used_at.
- **AuditLog** — append-only, partitioned by month, immutability trigger; composite PK (id, created_at).
- **Webhook / WebhookEvent** — endpoint + sealed secret; delivery attempts/status.
- **NotificationPreference** — notify_on_issuance/revocation/verification, channel, contacts.
- **DigiLockerPush** — attempt_count, status (pending|success|retrying|permanently_failed).
- **Anchor / Consent** — anchor batch/root records; consent records with notice version.

All tenant-scoped tables carry `tenant_id UUID NOT NULL` with RLS enabled and forced.
