# Security Patterns

## Authentication Overview

The platform supports three authentication flows:

| Flow | Audience | Endpoint | Token Type |
|------|----------|----------|-----------|
| OAuth 2.0 Client Credentials | API clients (issuers, integrations) | `POST /api/v1/auth/token` | RS256 JWT |
| OTP (One-Time Password) | Beneficiaries | `POST /api/v1/auth/otp/request` + `/verify` | RS256 JWT |
| MFA (TOTP) | Admin accounts | `POST /api/v1/auth/mfa/challenge` + `/verify` | RS256 JWT |

All flows result in an RS256-signed JWT with standard claims.

## JWT Structure

### Signing

- **Algorithm:** RS256 (RSA + SHA-256)
- **Library:** python-jose
- **Keys:** PEM-encoded RSA key pair configured via `JWT_PRIVATE_KEY` / `JWT_PUBLIC_KEY` env vars

### Token Claims

```json
{
  "sub": "<user_id or client_id>",
  "tenant_id": "<uuid>",
  "roles": ["issuer"],
  "iat": 1700000000,
  "exp": 1700003600
}
```

### Constraints

- Maximum lifetime: **3600 seconds** (enforced by config validation)
- Minimum lifetime: **60 seconds**
- Required claims: `sub`, `exp`, `tenant_id`

### Validation Dependency

`app/dependencies/auth.py` provides `get_current_user`:

```python
async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)],
) -> TokenPayload:
```

This dependency:
1. Extracts the Bearer token from the `Authorization` header
2. Decodes and validates the JWT (signature, expiry, required claims)
3. Returns a frozen `TokenPayload` dataclass
4. Stores `tenant_id` on `request.state` for downstream middleware
5. Raises HTTP 401 with `INVALID_TOKEN` or `TOKEN_EXPIRED` codes on failure

## OTP Authentication (Beneficiaries)

- 6-digit numeric code (configurable: 4-8 digits)
- Stored as bcrypt hash in Redis with TTL (default: 600 seconds / 10 minutes)
- **Single-use:** deleted from Redis after first successful verification
- **Rate limiting:** prevent brute-force via per-email attempt limits
- Response on request is always generic ("If an account exists, an OTP has been sent") to prevent user enumeration

## MFA (Admin Accounts)

- TOTP-based using `pyotp` (RFC 6238)
- `mfa_secret` stored on `user_accounts` table
- MFA challenge must be completed within **5 minutes** of initiation
- Required for `super_admin` and `tenant_admin` roles before elevated access is granted

## Account Lockout

### Standard Lockout (Auth Failures)

- **Threshold:** 5 consecutive failed attempts (configurable: `max_failed_auth_attempts`)
- **Duration:** 15 minutes (configurable: `auth_lockout_minutes`)
- Tracked via `failed_auth_attempts` column on `user_accounts` (also cached in Redis for performance)
- Counter resets on successful authentication

### Admin MFA Lockout

- **Threshold:** 3 consecutive failed MFA attempts (configurable: `max_failed_mfa_attempts`)
- **Duration:** 30 minutes (configurable: `mfa_lockout_minutes`)
- Notification sent to account owner on lockout

### Implementation Pattern

```python
# Check lockout before authentication attempt
if user.locked_until and user.locked_until > datetime.now(timezone.utc):
    raise HTTPException(status_code=401, detail={"code": "ACCOUNT_LOCKED", ...})

# Increment on failure
user.failed_auth_attempts += 1
if user.failed_auth_attempts >= settings.max_failed_auth_attempts:
    user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.auth_lockout_minutes)

# Reset on success
user.failed_auth_attempts = 0
user.locked_until = None
```

## Role-Based Access Control (RBAC)

### Roles

Five predefined roles with hierarchical permissions:

| Role | Scope | Description |
|------|-------|-------------|
| `super_admin` | Platform-wide | Manages tenants, all platform operations |
| `tenant_admin` | Single tenant | Manages schemas, users, documents within tenant |
| `issuer` | Single tenant | Uploads and manages documents |
| `beneficiary` | Single tenant | Views and shares own documents |
| `verifier` | Single tenant | Verifies document authenticity |

### Permission Map

Permissions follow the pattern `<resource>:<action>`:

```
tenant:create, tenant:read, tenant:update, tenant:suspend, tenant:deactivate
schema:create, schema:read, schema:update, schema:delete, schema:export
document:upload, document:read, document:download, document:list, document:revoke
document:bulk_upload, document:bulk_revoke
verification:create, verification:read
audit:read, audit:export
webhook:create, webhook:read, webhook:update, webhook:delete
notification:read, notification:update
user:create, user:read, user:update, user:delete
search:query
```

The full map is defined in `app/rbac/permissions.py` as `ROLE_PERMISSIONS: dict[str, set[str]]`.

### Enforcement

Use `require_permission()` as a FastAPI dependency:

```python
from app.rbac.permissions import require_permission

@router.post("/documents", dependencies=[Depends(require_permission("document:upload"))])
async def upload_document(...): ...
```

On denial:
- Returns HTTP 403 with `{"code": "FORBIDDEN", "message": "..."}`
- Logs the attempt at WARNING level (actor, attempted operation, target)
- Must respond within 2 seconds (Requirement 13.2)

### Adding New Permissions

1. Add the permission string to the relevant role(s) in `ROLE_PERMISSIONS`
2. Apply `require_permission("new:permission")` to the route
3. Document which requirement it satisfies

## Encryption

### At Rest — Envelope Encryption (AWS KMS)

Each tenant has a dedicated Customer Managed Key (CMK) in AWS KMS:

1. **Generate DEK:** Call KMS `GenerateDataKey` → returns plaintext DEK + encrypted DEK
2. **Encrypt document:** Use plaintext DEK with AES-256 to encrypt document content
3. **Store:** Upload ciphertext to S3; store encrypted DEK and IV in the `documents` table
4. **Discard:** Never persist the plaintext DEK

To decrypt:
1. Retrieve encrypted DEK from DB
2. Call KMS `Decrypt` → get plaintext DEK
3. Decrypt document content with the DEK

### At Rest — S3

- Server-Side Encryption with KMS (SSE-KMS) as additional layer
- Bucket policy enforces encryption on all PutObject requests

### In Transit

- TLS 1.2+ enforced on all API endpoints
- Internal service communication also uses TLS

### Key Rotation

- `tenant_encryption_keys` table tracks key status: `active`, `pending_rotation`, `disabled`
- Rotation creates a new key, re-encrypts active documents, then disables the old key
- Tracked via `rotated_at` timestamp

## API Key Management

### Client Credentials

- Stored in `api_clients` table with `client_secret_hash` (bcrypt)
- Rotation interval: configurable (default: 90 days, range: 1-365)
- Grace period: old key remains valid briefly after rotation
- Status lifecycle: `active` → `grace_period` → `revoked`

### Security Headers

Error responses include appropriate headers:
- `WWW-Authenticate: Bearer` on 401 responses
- `Retry-After` on 429 (rate limit) responses

## Rate Limiting

- Per-tenant rate limiting using Redis token bucket algorithm
- Default: 10,000 requests per 60-second window (configurable per tenant)
- Returns HTTP 429 with `Retry-After` header when exceeded
- Tenant-specific limits stored in `tenants.rate_limit_per_hour`

## Audit Trail

All security-relevant actions are logged to the immutable `audit_logs` table:

- Authentication attempts (success and failure)
- Permission denials (403 responses)
- Document access and modifications
- Configuration changes
- Account lockout events

Audit entries include: actor identity, action, target resource, tenant context, and UTC timestamp. The database trigger `prevent_audit_modification()` prevents any UPDATE or DELETE on audit records.

## Security Checklist for New Endpoints

When adding a new endpoint, verify:

1. JWT authentication is required (unless explicitly public)
2. RBAC permission check is applied via `require_permission()`
3. Tenant isolation is enforced (RLS context set before DB queries)
4. Input validation rejects malformed data (Pydantic models with constraints)
5. Error responses don't leak internal details
6. Audit log entry is created for state-changing operations
7. Rate limiting applies to the endpoint
8. Sensitive data (passwords, keys, tokens) is never logged or returned in responses
