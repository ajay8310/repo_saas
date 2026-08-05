# Implementation Plan: Generic Multi-Tenant SaaS Document and Credential Repository Platform

## Overview

Implement the platform incrementally using Python 3.12 / FastAPI, PostgreSQL 16 (RLS), Redis 7, Celery, AWS S3/KMS, and supporting services. Each task builds on the previous, wiring components together progressively. The implementation follows the component structure in the design document.

## Tasks

- [ ] 1. Project scaffolding, database schema, and core infrastructure
  - [x] 1.1 Initialize FastAPI project structure, dependency management, and configuration
    - Create project layout: `app/`, `tests/unit/`, `tests/property/`, `tests/integration/`, `tests/smoke/`
    - Set up `pyproject.toml` with dependencies: fastapi, uvicorn, sqlalchemy, alembic, asyncpg, redis, celery, boto3, hypothesis, pytest, pytest-asyncio
    - Create `app/config.py` with Pydantic `BaseSettings` for all environment variables (DB URL, Redis URL, AWS region/KMS, JWT keys, etc.)
    - Create `app/main.py` with FastAPI app factory, CORS middleware, and health-check endpoint `GET /health`
    - _Requirements: 8.1, 14.1_

  - [-] 1.2 Create database migrations for all core tables
    - Write Alembic migration for: `tenants`, `tenant_encryption_keys`, `api_clients`, `user_accounts`, `document_schemas`, `schema_versions`, `documents`, `bulk_jobs`, `verification_tokens`, `audit_logs`, `webhooks`, `webhook_events`, `notification_preferences`, `digilocker_pushes`
    - Add `tenant_id UUID NOT NULL` column to all tenant-scoped tables
    - Apply `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY` to all tenant-scoped tables
    - Apply RLS policy `CREATE POLICY tenant_isolation ON <table> USING (tenant_id = current_setting('app.tenant_id')::uuid) WITH CHECK (...)` to each table
    - Create `prevent_audit_modification()` trigger function and `audit_immutable` trigger on `audit_logs`
    - Create `tenant_storage_usage` materialized view and `check_quota_before_insert()` trigger function on `documents`
    - Partition `audit_logs` table by month (`PARTITION BY RANGE (created_at)`)
    - _Requirements: 7.1, 7.3, 7.4, 10.2, 10.4, 3.7_

  - [~] 1.3 Implement SQLAlchemy async models and database session middleware
    - Define async SQLAlchemy models for all tables in `app/models/`
    - Create `app/db/session.py` with async engine, session factory, and `get_db` dependency
    - Implement `TenantContextMiddleware` in `app/middleware/tenant_context.py` that sets `app.tenant_id` via `SET LOCAL app.tenant_id = '...'` at the start of every transaction
    - _Requirements: 7.1, 7.2_


- [ ] 2. Authentication Service
  - [~] 2.1 Implement OAuth 2.0 client credentials flow and JWT issuance
    - Create `app/services/auth_service.py` with `issue_token(client_id, client_secret) -> TokenResponse`
    - Generate RS256-signed JWTs with `iat`, `exp` (≤ 3600s), `sub`, `tenant_id`, `roles` claims
    - Store `client_secret_hash` using bcrypt; validate on token request
    - Implement `POST /api/v1/auth/token` endpoint (grant_type=client_credentials)
    - Implement JWT validation dependency `get_current_user` in `app/dependencies/auth.py`
    - Return HTTP 401 with `TOKEN_EXPIRED` / `INVALID_TOKEN` codes on failure
    - _Requirements: 8.2, 8.3_

  - [ ]* 2.2 Write property test for JWT expiry bound (Property 27)
    - **Property 27: JWT Expiry Bounded at 3600 Seconds**
    - **Validates: Requirements 8.2**

  - [ ]* 2.3 Write property test for expired JWT returns 401 (Property 28)
    - **Property 28: Expired JWT Returns 401**
    - **Validates: Requirements 8.3**

  - [~] 2.4 Implement OTP-based authentication for beneficiaries
    - Implement `POST /api/v1/auth/otp/request` — generate 6-digit code, store bcrypt hash in Redis with 600s TTL
    - Implement `POST /api/v1/auth/otp/verify` — validate code, mark used (delete from Redis), return JWT
    - Ensure OTP is invalidated after first use or after 10 minutes
    - _Requirements: 4.5, 4.6_

  - [ ]* 2.5 Write property test for OTP single-use and expiry enforcement (Property 17)
    - **Property 17: OTP Single-Use and Expiry Enforcement**
    - **Validates: Requirements 4.6**

  - [~] 2.6 Implement MFA (TOTP) for admin accounts
    - Implement `POST /api/v1/auth/mfa/challenge` and `POST /api/v1/auth/mfa/verify` using `pyotp` (RFC 6238)
    - Require MFA step within 5 minutes; deny access if not completed in time
    - Store `mfa_secret` on `user_accounts`; require enrollment before first admin login
    - _Requirements: 13.3_

  - [ ]* 2.7 Write property test for MFA required for admin roles (Property 40)
    - **Property 40: MFA Required for Admin Roles**
    - **Validates: Requirements 13.3**

  - [~] 2.8 Implement account lockout logic
    - Track `failed_auth_attempts` and `locked_until` on `user_accounts` (also cache in Redis)
    - Lock account for 15 minutes after 5 consecutive failed attempts within 10 minutes
    - Lock admin account for 30 minutes after 3 consecutive failed MFA attempts
    - Notify account owner on lockout via notification service
    - _Requirements: 13.6, 13.8_

  - [ ]* 2.9 Write property test for account lockout after 5 failed attempts (Property 42)
    - **Property 42: Account Lockout After 5 Failed Attempts**
    - **Validates: Requirements 13.6**

  - [ ]* 2.10 Write property test for MFA account lockout after 3 failed MFA attempts (Property 43)
    - **Property 43: MFA Account Lockout After 3 Failed MFA Attempts**
    - **Validates: Requirements 13.8**

- [~] 3. Checkpoint — Ensure all auth tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 4. RBAC middleware and error handling infrastructure
  - [~] 4.1 Implement RBAC permission enforcement middleware
    - Define role permission map in `app/rbac/permissions.py` for roles: `super_admin`, `tenant_admin`, `issuer`, `beneficiary`, `verifier`
    - Implement `require_permission(operation)` FastAPI dependency that returns HTTP 403 `FORBIDDEN` within 2 seconds if role lacks permission
    - Write audit log entry (actor, attempted operation, target resource, UTC timestamp) on every 403
    - _Requirements: 13.1, 13.2_

  - [ ]* 4.2 Write property test for RBAC permission enforcement (Property 39)
    - **Property 39: RBAC Permission Enforcement**
    - **Validates: Requirements 13.1, 13.2**

  - [~] 4.3 Implement global error response format and HTTP 422 validation handler
    - Create `app/errors/handlers.py` with FastAPI exception handlers for all error codes in the taxonomy
    - Override FastAPI's default `RequestValidationError` handler to return HTTP 422 with field name, rejected value, and human-readable description for each invalid field
    - _Requirements: 8.6_

  - [ ]* 4.4 Write property test for HTTP 422 with field-level errors (Property 29)
    - **Property 29: HTTP 422 with Field-Level Errors for Invalid Payloads**
    - **Validates: Requirements 8.6**

  - [~] 4.5 Implement tenant status middleware (suspension / deactivation guards)
    - In `TenantContextMiddleware`, after JWT validation, look up tenant status from Redis cache (TTL 5s)
    - Return `403 TENANT_SUSPENDED` for suspended tenants; allow reads but reject writes for deactivated (archived) tenants
    - _Requirements: 1.5, 1.6_


- [ ] 5. Rate Limiter
  - [~] 5.1 Implement per-tenant Redis token-bucket rate limiter
    - Create `app/services/rate_limiter.py` implementing a sliding-window counter in Redis
    - Default: 10,000 requests per 60-second rolling window; per-tenant override via `tenants.rate_limit_per_hour`
    - Return HTTP 429 with `Retry-After` header (seconds until window reset) when quota exceeded
    - Implement `RateLimitMiddleware` and wire into FastAPI app
    - _Requirements: 1.9, 8.4_

  - [ ]* 5.2 Write property test for rate limit — HTTP 429 with Retry-After at limit (Property 4)
    - **Property 4: Rate Limit — HTTP 429 with Retry-After at Limit**
    - **Validates: Requirements 1.9, 8.4**

- [ ] 6. Tenant Service
  - [~] 6.1 Implement tenant onboarding and lifecycle management
    - Create `app/services/tenant_service.py` with `create_tenant()`, `approve_tenant()`, `suspend_tenant()`, `deactivate_tenant()`
    - Validate domain uniqueness across all lifecycle states; return `409 DOMAIN_CONFLICT` on duplicate
    - On create: insert tenant in `pending` state, call KMS `create_key()`, store ARN in `tenant_encryption_keys`, generate `client_id`/`client_secret` (bcrypt hash), return credentials
    - Implement lifecycle state machine: `pending → active` (Super_Admin approval only), `active → suspended`, `active/suspended → deactivated`
    - Invalidate Redis tenant status cache on any state change
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6_

  - [ ]* 6.2 Write property test for tenant namespace global uniqueness (Property 1)
    - **Property 1: Tenant Namespace Global Uniqueness**
    - **Validates: Requirements 1.1, 1.3**

  - [ ]* 6.3 Write property test for deactivated tenant write rejection (Property 2)
    - **Property 2: Deactivated Tenant Write Rejection**
    - **Validates: Requirements 1.6**

  - [~] 6.4 Implement per-tenant quota and rate limit configuration
    - Add `PATCH /api/v1/admin/tenants/{id}` endpoint for Super_Admin to set storage quota, rate limit, and allowed schema categories
    - Validate quota range (1 MB–10 TB), rate limit range (1–1,000,000 req/hr), schema categories (≤ 100)
    - _Requirements: 1.7, 1.8_

  - [~] 6.5 Implement API key rotation with grace period
    - Add `POST /api/v1/admin/tenants/{id}/rotate-key` endpoint
    - On rotation: generate new `client_id`/`client_secret`, set `grace_until = now() + grace_hours`, keep old key valid until grace period expires
    - Validate rotation interval in range [1, 365] days; reject out-of-range values with descriptive error
    - _Requirements: 13.4, 13.9_

  - [ ]* 6.6 Write property test for API key grace period — both keys accepted (Property 41)
    - **Property 41: API Key Grace Period — Both Keys Accepted**
    - **Validates: Requirements 13.4**

  - [ ]* 6.7 Write property test for API key rotation interval validation (Property 44)
    - **Property 44: API Key Rotation Interval Validation**
    - **Validates: Requirements 13.9**

- [~] 7. Checkpoint — Ensure all tenant and auth tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 8. Schema Service
  - [~] 8.1 Implement document schema CRUD with field validation
    - Create `app/services/schema_service.py` with `create_schema()`, `update_schema()`, `deactivate_schema()`
    - Validate each field definition: `name` (non-empty string), `type` (string|number|date|boolean|enumeration|file_reference), `required` (boolean); enumeration fields must have non-empty `allowed_values`
    - Return `422 SCHEMA_INVALID` with field-level errors on invalid definitions
    - Enforce namespace isolation: reject operations targeting schemas outside the authenticated tenant namespace
    - Implement endpoints: `POST /api/v1/schemas`, `GET /api/v1/schemas/{id}`, `PATCH /api/v1/schemas/{id}`, `DELETE /api/v1/schemas/{id}`
    - _Requirements: 2.1, 2.2, 2.5, 2.6_

  - [ ]* 8.2 Write property test for schema field validation rejects invalid definitions (Property 6)
    - **Property 6: Schema Field Validation Rejects Invalid Definitions**
    - **Validates: Requirements 2.2**

  - [ ]* 8.3 Write property test for schema CRUD namespace isolation (Property 5)
    - **Property 5: Schema CRUD Namespace Isolation**
    - **Validates: Requirements 2.1, 7.1, 7.2**

  - [~] 8.4 Implement schema version management and breaking-change detection
    - On update: insert current field_definitions into `schema_versions`, increment version monotonically (new_version = old_version + 1)
    - Run dry-run re-validation of all documents under the current schema version; if any fail, reject with list of conflicting `credential_id` values and `409 SCHEMA_BREAKING_CHANGE`
    - Implement `GET /api/v1/schemas/{id}/versions` to return full version history
    - _Requirements: 2.3, 2.4_

  - [ ]* 8.5 Write property test for breaking schema update rejection (Property 7)
    - **Property 7: Breaking Schema Update Rejection**
    - **Validates: Requirements 2.3**

  - [ ]* 8.6 Write property test for schema version monotonic increment (Property 8)
    - **Property 8: Schema Version Monotonic Increment**
    - **Validates: Requirements 2.4**

  - [~] 8.7 Implement schema JSON export endpoint
    - Implement `GET /api/v1/schemas/{id}/export` returning JSON with `version`, `field_definitions`, and `created_at`
    - _Requirements: 2.7_

  - [ ]* 8.8 Write property test for schema export round-trip (Property 9)
    - **Property 9: Schema Export Round-Trip**
    - **Validates: Requirements 2.7**


- [ ] 9. Encryption Service
  - [~] 9.1 Implement per-tenant envelope encryption using AWS KMS
    - Create `app/services/encryption_service.py` implementing `encrypt(tenant_id, plaintext) -> EncryptedPayload` and `decrypt(tenant_id, payload) -> bytes`
    - Per document: generate 256-bit DEK locally, encrypt content with AES-256-GCM (unique IV), encrypt DEK with tenant's CMK via KMS `Encrypt` API
    - Return `EncryptedPayload(encrypted_dek, iv, ciphertext, tenant_cmk_arn)`
    - Return `503 SERVICE_UNAVAILABLE` if KMS is unreachable; never expose plaintext
    - _Requirements: 3.6, 7.3, 13.7_

- [ ] 10. Audit Log Service
  - [~] 10.1 Implement append-only audit log service
    - Create `app/services/audit_log_service.py` with `record(entry: AuditEntry) -> None`
    - Write audit entries within the same PostgreSQL transaction as the originating operation (transactional outbox pattern)
    - Roll back the originating operation if the audit INSERT fails; return `500` with `audit_write_failed` code
    - Implement `GET /api/v1/audit-logs` for Tenant_Admin queries scoped to their namespace
    - _Requirements: 10.1, 10.2, 10.7_

  - [ ]* 10.2 Write property test for audit log entry immutability (Property 35)
    - **Property 35: Audit Log Entry Immutability**
    - **Validates: Requirements 10.2**

  - [ ]* 10.3 Write property test for audit log namespace isolation (Property 36)
    - **Property 36: Audit Log Namespace Isolation**
    - **Validates: Requirements 10.3**

  - [ ]* 10.4 Write property test for audit log write failure rejects originating operation (Property 37)
    - **Property 37: Audit Log Write Failure Rejects Originating Operation**
    - **Validates: Requirements 10.7**

  - [~] 10.5 Implement audit log export (JSON and CSV)
    - Add `GET /api/v1/audit-logs/export?format=json|csv` endpoint
    - Support up to 100,000 entries; stream response to complete within 60 seconds
    - _Requirements: 10.5_

  - [ ]* 10.6 Write property test for audit log written for every document retrieval (Property 19)
    - **Property 19: Audit Log Written for Every Document Retrieval**
    - **Validates: Requirements 4.9, 10.1**

- [~] 11. Checkpoint — Ensure all schema, encryption, and audit log tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 12. Document Service — single upload, retrieval, and revocation
  - [~] 12.1 Implement single document upload endpoint
    - Create `app/services/document_service.py` with `upload_document(tenant_id, schema_id, payload, beneficiary_id)`
    - Validate schema exists, belongs to tenant, and is active; validate payload fields against schema (type, required, enum values); validate `beneficiary_id` is non-empty
    - Encrypt content via EncryptionService; store to S3 at `s3://{tenant_id}/{credential_id}`; insert metadata row into `documents`
    - Check storage quota via `check_quota_before_insert()` trigger; reject with `507 QUOTA_EXCEEDED` including current usage and limit if exceeded
    - Enqueue async audit log entry (must complete within 5s), search index update (within 5s), DigiLocker push (if enabled), and notification (if enabled)
    - Return `{ credential_id, status: "stored" }` within 3 seconds under normal load
    - Apply 30-second request timeout; guarantee no partial data on timeout
    - Implement `POST /api/v1/documents`
    - _Requirements: 3.1, 3.3, 3.4, 3.5, 3.6, 3.7, 3.11_

  - [ ]* 12.2 Write property test for document upload assigns unique credential IDs (Property 10)
    - **Property 10: Document Upload Assigns Unique Credential IDs**
    - **Validates: Requirements 3.1**

  - [ ]* 12.3 Write property test for invalid document upload — no partial storage (Property 12)
    - **Property 12: Invalid Document Upload — No Partial Storage**
    - **Validates: Requirements 3.3, 3.4**

  - [ ]* 12.4 Write property test for quota enforcement (Property 3)
    - **Property 3: Quota Enforcement — All Uploads Rejected at Quota**
    - **Validates: Requirements 1.8, 3.7**

  - [~] 12.5 Implement document retrieval and download endpoints
    - Implement `GET /api/v1/documents/{id}` — validate beneficiary identity matches document's `beneficiary_id`; return `403` (indistinguishable from not-found) if mismatch or if document does not exist
    - Implement `GET /api/v1/documents/{id}/download` — decrypt document, generate digitally signed PDF (`reportlab`/`weasyprint`) or JSON-LD (`PyLD`) with embedded `credential_id` and QR code (verification URL); deliver within 10 seconds
    - Implement `GET /api/v1/documents` for Issuer/Tenant_Admin — list with pagination, scoped to tenant namespace
    - Write audit log entry for every retrieval attempt (success or failure)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.7, 4.8, 4.9_

  - [ ]* 12.6 Write property test for document access authorization — indistinguishable error (Property 16)
    - **Property 16: Document Access Authorization — Indistinguishable Error**
    - **Validates: Requirements 4.2, 4.3, 4.4**

  - [ ]* 12.7 Write property test for beneficiary document list isolation (Property 15)
    - **Property 15: Beneficiary Document List Isolation**
    - **Validates: Requirements 4.1, 7.1**

  - [ ]* 12.8 Write property test for downloaded document contains credential ID and QR code (Property 18)
    - **Property 18: Downloaded Document Contains Credential ID and QR Code**
    - **Validates: Requirements 4.7**

  - [~] 12.9 Implement document revocation endpoint
    - Implement `POST /api/v1/documents/{id}/revoke` — validate Credential_ID belongs to authenticated tenant's namespace; set status to `revoked`, record `revoked_at` (UTC ISO 8601), store `revocation_reason` (1–500 chars)
    - Return `409 ALREADY_REVOKED` if document is already revoked
    - Return `403` if Credential_ID belongs to another tenant namespace
    - Enqueue revocation notification to beneficiary (within 60 seconds)
    - _Requirements: 6.1, 6.2, 6.4, 6.5_

  - [ ]* 12.10 Write property test for revocation state transition (Property 24)
    - **Property 24: Revocation State Transition**
    - **Validates: Requirements 6.1**

  - [ ]* 12.11 Write property test for double revocation idempotence (Property 25)
    - **Property 25: Double Revocation Idempotence (Error)**
    - **Validates: Requirements 6.2**

  - [ ]* 12.12 Write property test for cross-tenant revocation rejection (Property 26)
    - **Property 26: Cross-Tenant Revocation Rejection**
    - **Validates: Requirements 6.4**

  - [~] 12.13 Implement bulk revocation endpoint
    - Implement `POST /api/v1/documents/bulk-revoke` — accept up to 1,000 Credential_IDs; process each independently
    - Return per-item result: `revoked`, `already-revoked`, `not-found`, or `unauthorized`
    - Valid revocations proceed even when other items in the batch fail
    - _Requirements: 6.6, 6.7_

  - [ ]* 12.14 Write property test for bulk upload record independence — applied to bulk revocation (Property 11)
    - **Property 11: Bulk Upload Record Independence**
    - **Validates: Requirements 3.2, 6.7**


- [ ] 13. Bulk Upload Pipeline
  - [~] 13.1 Implement bulk upload API endpoint and job creation
    - Implement `POST /api/v1/documents/bulk` — validate file format (CSV or JSON only) and record count (≤ 10,000) before processing any records; reject entire request immediately with `413 BATCH_TOO_LARGE` or `415 UNSUPPORTED_FORMAT`
    - Insert `bulk_jobs` record (status=pending), enqueue Celery task, return `202 { job_id }` within 5 seconds
    - Implement `GET /api/v1/documents/bulk/{job_id}` — return status (`pending`, `in-progress`, `completed`, `failed`), processed count, failed count
    - _Requirements: 3.2, 3.8, 3.9, 14.3, 14.4_

  - [ ]* 13.2 Write property test for bulk upload size boundary (Property 13)
    - **Property 13: Bulk Upload Size Boundary**
    - **Validates: Requirements 3.8, 3.9**

  - [~] 13.3 Implement Celery worker for bulk record processing
    - Create `app/tasks/bulk_upload.py` Celery task that processes each record in an independent savepoint
    - Validate each record against schema, encrypt via EncryptionService, store to S3, insert document row, update job progress counter in Redis
    - On completion: write final summary to `bulk_jobs` table; summary must include `total_records`, `success_count`, `failed_count`, list of `credential_id` values for successes, per-record error details (record index, field name, error reason) for failures
    - Full processing of 10,000 records must complete within 30 minutes
    - _Requirements: 3.2, 3.10, 14.4_

  - [ ]* 13.4 Write property test for bulk upload summary report completeness (Property 14)
    - **Property 14: Bulk Upload Summary Report Completeness**
    - **Validates: Requirements 3.10**

- [~] 14. Checkpoint — Ensure all document service and bulk upload tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 15. Verification Service
  - [~] 15.1 Implement verification token generation
    - Create `app/services/verification_service.py` with `generate_token(beneficiary_id, credential_id, consented_fields, expiry_hours)`
    - Validate credential belongs to authenticated beneficiary; validate `expiry_hours` in range [1, 168] (default 72)
    - Generate 32-byte cryptographically random token (URL-safe base64); store SHA-256 hash in `verification_tokens` with `consented_fields`, `expires_at`, `used_at=null`
    - Return token + expiry to beneficiary
    - Implement `POST /api/v1/verifications/tokens`
    - _Requirements: 5.1_

  - [ ]* 15.2 Write property test for verification token expiry bound (Property 20)
    - **Property 20: Verification Token Expiry Bound**
    - **Validates: Requirements 5.1, 5.3**

  - [~] 15.3 Implement verification token consumption endpoint
    - Implement `GET /api/v1/verifications/{token}` — compute SHA-256 of submitted token, look up hash
    - Validate: not found → `410 TOKEN_INVALID`; `used_at IS NOT NULL` → `410 TOKEN_USED`; `expires_at < now()` → `401 OTP_EXPIRED` (token-expired); else mark `used_at = now()` atomically
    - Return `{ valid: true, issuer_name, issued_at, fields: { only consented_fields } }`; if consented_fields is empty, return only validity status and issuer name
    - Return revoked status and revocation timestamp if document is revoked
    - Write audit log entry for every verification attempt
    - _Requirements: 5.2, 5.3, 5.4, 5.5, 5.8, 5.9, 6.3_

  - [ ]* 15.4 Write property test for verification consent field enforcement (Property 21)
    - **Property 21: Verification Consent Field Enforcement**
    - **Validates: Requirements 5.2, 5.8**

  - [ ]* 15.5 Write property test for invalid/used/expired token — no document data leakage (Property 22)
    - **Property 22: Invalid/Used/Expired Token — No Document Data Leakage**
    - **Validates: Requirements 5.3, 5.4, 5.5**

  - [~] 15.6 Implement public verification endpoints
    - Implement `GET /api/v1/verify/{credential_id}` (unauthenticated) — return only validity status (`valid`, `invalid`, or `revoked`); no document fields, no beneficiary details
    - Implement `GET /api/v1/verify/qr/{token}` (public HTML page) — display validity status, issuing tenant name, and beneficiary-consented fields; no Verifier authentication required
    - _Requirements: 5.6, 5.7, 5.10_

  - [ ]* 15.7 Write property test for public verification endpoint — validity status only (Property 23)
    - **Property 23: Public Verification Endpoint — Validity Status Only**
    - **Validates: Requirements 5.10**


- [ ] 16. Search Service
  - [~] 16.1 Implement per-tenant document search API
    - Create `app/services/search_service.py` using PostgreSQL `pg_trgm` + GIN indexes for full-text and faceted search
    - Support filters: beneficiary ID (full-text), schema type, status, `issued_after`, `issued_before`; sorting by issuance date, status, schema type (ascending/descending); pagination (1–100 per page, default 20)
    - Validate date range filter: reject with `422 INVALID_DATE_RANGE` if `start_date > end_date`
    - Return empty result set with HTTP 200 when no results found
    - All queries scoped to authenticated tenant namespace via RLS
    - Implement `GET /api/v1/documents?q=...` with all filter/sort/pagination params
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 9.7_

  - [ ]* 16.2 Write property test for search results namespace isolation (Property 32)
    - **Property 32: Search Results Namespace Isolation**
    - **Validates: Requirements 9.2, 7.1**

  - [ ]* 16.3 Write property test for search results sort order correctness (Property 33)
    - **Property 33: Search Results Sort Order Correctness**
    - **Validates: Requirements 9.4**

  - [ ]* 16.4 Write property test for invalid date range returns HTTP 422 (Property 34)
    - **Property 34: Invalid Date Range Returns HTTP 422**
    - **Validates: Requirements 9.7**

- [ ] 17. Notification Service
  - [~] 17.1 Implement event-driven notification delivery
    - Create `app/services/notification_service.py` with pluggable adapters for AWS SES (email) and AWS SNS (SMS)
    - Before sending, check `beneficiary_notification_preferences` for enabled event types and preferred channel; skip and log `skipped-notification` audit entry if disabled or no contact on file
    - Implement Celery retry policy: up to 3 retries at 30s, 60s, 120s exponential backoff (`max_retries=3`, `countdown` sequence); write final delivery status (delivered/permanently_failed) to `notification_log` and audit log
    - Create `app/tasks/notifications.py` Celery tasks for: issuance notification, revocation notification, verification-access notification
    - _Requirements: 11.1, 11.2, 11.3, 11.5, 11.6_

  - [ ]* 17.2 Write property test for notification preference enforcement (Property 38)
    - **Property 38: Notification Preference Enforcement**
    - **Validates: Requirements 11.4_

  - [~] 17.3 Implement notification preference management endpoints
    - Implement `GET /api/v1/beneficiaries/me/notification-preferences` and `PATCH /api/v1/beneficiaries/me/notification-preferences`
    - Allow beneficiaries to enable/disable each event type (issuance, revocation, verification) and select preferred channel (email or SMS)
    - _Requirements: 11.4_

- [~] 18. Checkpoint — Ensure all verification, search, and notification tests pass
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 19. Webhook Service
  - [~] 19.1 Implement webhook registry and event delivery
    - Create `app/services/webhook_service.py` with webhook registration CRUD for tenants
    - On qualifying events (document uploaded, revoked, verified): look up active webhooks for tenant, serialize event payload as JSON, compute `HMAC-SHA256(webhook_secret, payload_bytes)` and include in `X-Webhook-Signature` header
    - Implement Celery retry task: first retry 5–10s after initial failure, each subsequent retry doubles the interval, max 3 retries
    - On exhaustion: mark event as `undelivered` in `webhook_events`, surface in Tenant_Admin dashboard within 60s
    - _Requirements: 8.7, 8.8, 8.9_

  - [ ]* 19.2 Write property test for webhook HMAC signature integrity (Property 30)
    - **Property 30: Webhook HMAC Signature Integrity**
    - **Validates: Requirements 8.7**

  - [ ]* 19.3 Write property test for webhook retry exponential backoff (Property 31)
    - **Property 31: Webhook Retry Exponential Backoff**
    - **Validates: Requirements 8.8, 8.9**

- [ ] 20. DigiLocker Connector
  - [~] 20.1 Implement DigiLocker async push with retry logic
    - Create `app/services/digilocker_connector.py` implementing DigiLocker issuer API (OAuth 2.0 authorization code flow)
    - On document issuance with connector enabled: enqueue push task within 10 seconds
    - Celery task: attempt push; on failure retry up to 5 times at minimum 60s intervals (`countdown=60, max_retries=5`)
    - If beneficiary has no linked DigiLocker account: fail immediately without retry, log reason in audit log
    - On all retries exhausted: mark `digilocker_pushes.status = 'permanently_failed'`, notify tenant_admin, write audit entry
    - Log each attempt: document ID, beneficiary ID, attempt timestamp, attempt number, outcome
    - Per-tenant connector enable/disable without platform-level changes
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

- [ ] 21. Malware Scanning
  - [~] 21.1 Implement file malware scan integration
    - Create `app/services/malware_scanner.py` with `scan(file_content: bytes) -> ScanResult`
    - Integrate ClamAV sidecar (via `clamd` library) or AWS GuardDuty file scan
    - Reject uploaded files that fail the scan with a reason-included error response; guarantee no rejected file content is persisted
    - If scan service is unavailable, reject upload with `503 SERVICE_UNAVAILABLE` — never bypass the scan
    - Wire scan call into the single document upload flow before encryption/storage
    - _Requirements: 13.5_

- [ ] 22. Anomalous Access Detection
  - [~] 22.1 Implement anomalous access pattern detection and alerting
    - Create `app/tasks/anomaly_detection.py` Celery periodic task (runs every minute)
    - Track document retrievals per identity using a Redis sliding-window counter (10-minute window)
    - When threshold of 500 retrievals is exceeded: generate alert to Tenant_Admin within 5 minutes of threshold crossing (via notification service), write alert entry to audit log
    - _Requirements: 10.6_

- [ ] 23. OpenAPI specification
  - [~] 23.1 Configure and expose OpenAPI 3.0 specification
    - Configure FastAPI to generate OpenAPI 3.0 spec at `/api/v1/openapi.json` covering all endpoints with parameters, request schemas, and response schemas
    - Add response model annotations to all endpoints for complete schema coverage
    - Wire OpenAPI spec update into the deployment pipeline so it stays current within one deployment cycle
    - _Requirements: 8.5_

- [~] 24. Checkpoint — Ensure all service tests pass end-to-end
  - Ensure all tests pass, ask the user if questions arise.


- [ ] 25. Property test infrastructure and Hypothesis strategies
  - [~] 25.1 Set up Hypothesis configuration and shared test strategies
    - Create `tests/property/conftest.py` with Hypothesis settings profile `ci` (`max_examples=100`, `suppress_health_check=[HealthCheck.too_slow]`)
    - Implement reusable Hypothesis strategies in `tests/property/strategies.py`: `tenant_namespaces`, `field_definitions`, `valid_document_payload`, `role_operation_pairs`, `jwt_claims`, `token_strings`
    - _Requirements: (testing infrastructure)_

  - [ ]* 25.2 Implement all Tier 1 property tests (pure functions, no I/O)
    - Create `tests/property/test_tenant_properties.py` — Properties 1, 2
    - Create `tests/property/test_schema_properties.py` — Properties 5, 6, 7, 8, 9
    - Create `tests/property/test_document_properties.py` — Properties 10, 11, 12, 13, 14, 15, 16
    - Create `tests/property/test_verification_properties.py` — Properties 17, 18, 20, 21, 22, 23, 24, 25, 26
    - Create `tests/property/test_auth_properties.py` — Properties 27, 28, 40, 41, 42, 43, 44
    - Create `tests/property/test_rbac_properties.py` — Properties 29, 39
    - Create `tests/property/test_audit_properties.py` — Properties 35, 36
    - Create `tests/property/test_search_properties.py` — Properties 30, 31, 32, 33, 34
    - _Requirements: (all 44 correctness properties)_

  - [ ]* 25.3 Implement all Tier 2 property tests (service layer with DB mocks)
    - Implement Properties 2, 3, 4, 19, 32, 37 with mocked DB and Redis using `unittest.mock` / `pytest-mock`
    - _Requirements: 1.6, 1.8, 1.9, 4.9, 9.2, 10.7_

- [ ] 26. Integration tests and deployment configuration
  - [ ]* 26.1 Set up Docker Compose test environment and integration test fixtures
    - Create `docker-compose.test.yml` with PostgreSQL 16, Redis 7, LocalStack (for S3, KMS, SES, SNS)
    - Create `tests/integration/conftest.py` with fixtures for DB sessions, Celery worker, LocalStack clients
    - _Requirements: (integration test infrastructure)_

  - [ ]* 26.2 Implement integration tests for core platform flows
    - Create `tests/integration/test_tenant_lifecycle.py` — tenant provisioning end-to-end within 60s (Req 1.2); suspension access denial within 10s (Req 1.5)
    - Create `tests/integration/test_rls_isolation.py` — cross-tenant RLS read/write isolation checks (Req 7.1, 7.6)
    - Create `tests/integration/test_bulk_upload.py` — 10,000 records processed within 30 minutes (Req 14.4)
    - Create `tests/integration/test_search_performance.py` — search p95 < 3s with 10k documents (Req 9.3)
    - Create `tests/integration/test_digilocker_connector.py` — 5 retries at 60s intervals (Req 12.2)
    - Create `tests/integration/test_notification_delivery.py` — revocation notification within 60s (Req 6.5)
    - Create `tests/integration/test_post_deployment_checks.py` — automated cross-tenant isolation checks, alert within 1 minute on violation (Req 7.6, 7.7)
    - _Requirements: 1.2, 1.5, 6.5, 7.1, 7.6, 7.7, 9.3, 12.2, 14.4_

  - [ ]* 26.3 Implement smoke tests for post-deployment verification
    - Create `tests/smoke/test_deployment_smoke.py` — verify all `/api/v1/` endpoints respond, OpenAPI spec is valid OpenAPI 3.0, KMS keys exist and enabled per tenant, RLS policies active on all tables, audit log retention ≥ 7 years, AES-256 at rest + TLS 1.2+ in transit
    - _Requirements: 3.6, 7.1, 7.3, 8.1, 8.5, 10.4, 13.7_

- [~] 27. Final checkpoint — Full test suite passes
  - Ensure all tests pass, ask the user if questions arise.


## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- All 44 correctness properties from the design document are covered by property test sub-tasks
- Checkpoints ensure incremental validation after each major component group
- Property tests use Hypothesis (Python) with `max_examples=100` in CI profile
- Integration tests require Docker Compose with LocalStack; run separately from unit/property tests
- The transactional outbox pattern (tasks 10.1, 1.2) ensures no operation completes without a corresponding audit record
- All tenant-scoped tables use PostgreSQL RLS with `SET LOCAL app.tenant_id` per transaction — enforced at DB level below the ORM
- Encryption uses AWS KMS envelope encryption: one CMK per tenant, unique DEK per document

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2"] },
    { "id": 2, "tasks": ["1.3"] },
    { "id": 3, "tasks": ["2.1", "4.3", "9.1", "10.1"] },
    { "id": 4, "tasks": ["2.2", "2.3", "2.4", "4.1", "4.4", "4.5", "10.2", "10.3", "10.4", "10.5"] },
    { "id": 5, "tasks": ["2.5", "2.6", "4.2", "5.1", "6.1", "10.6"] },
    { "id": 6, "tasks": ["2.7", "2.8", "5.2", "6.2", "6.3", "6.4"] },
    { "id": 7, "tasks": ["2.9", "2.10", "6.5", "8.1"] },
    { "id": 8, "tasks": ["6.6", "6.7", "8.2", "8.3", "25.1"] },
    { "id": 9, "tasks": ["8.4", "12.1"] },
    { "id": 10, "tasks": ["8.5", "8.6", "8.7", "12.2", "12.3", "12.4", "12.5", "13.1"] },
    { "id": 11, "tasks": ["8.8", "12.6", "12.7", "12.8", "12.9", "13.2", "13.3", "16.1", "17.1", "19.1", "21.1"] },
    { "id": 12, "tasks": ["12.10", "12.11", "12.12", "12.13", "13.4", "16.2", "16.3", "16.4", "17.2", "17.3", "19.2", "19.3", "20.1", "22.1", "23.1"] },
    { "id": 13, "tasks": ["12.14", "15.1", "25.2", "25.3"] },
    { "id": 14, "tasks": ["15.2", "15.3"] },
    { "id": 15, "tasks": ["15.4", "15.5", "15.6"] },
    { "id": 16, "tasks": ["15.7", "26.1"] },
    { "id": 17, "tasks": ["26.2", "26.3"] }
  ]
}
```
