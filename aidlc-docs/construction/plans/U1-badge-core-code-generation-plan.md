# U1 Badge Core — Code Generation Plan

**Single source of truth for U1 code generation.** Full-stack (Q3=B). Brownfield: modify existing
files in place; create new ones as listed. Application code at workspace root (never aidlc-docs/).

## Unit Context
- **Stories**: S1 (create/edit BadgeClass), S2 (image upload), S3 (issuer profile), S4 (issue),
  S5 (bulk issue), S6 (revoke), S13 (fetch & verify hosted assertion).
- **Dependencies**: reuse documents/audit/anchoring/encryption/S3, notification, RLS, malware scan.
- **Entities owned**: `badge_classes`, `badge_assertions` (partitioned), `badge_events` (partitioned,
  brought forward), issuer profile fields on tenant.
- **Design refs**: U1 functional-design/*, nfr-design-patterns.md, infrastructure-design.md, shared-infrastructure.md.

## Steps

### Backend — Models & Migration
- [x] **Step 1** — Models `app/models/badge.py`: `BadgeClass` (UUIDPrimaryKeyMixin+Timestamp),
  `BadgeAssertion` (composite PK `(id, issued_at)`, UNIQUE(id), FK badge_class + document),
  `BadgeEvent` (composite PK `(id, created_at)`). Register in `app/models/__init__.py`.
- [x] **Step 2** — Issuer profile: add `issuer_name`, `issuer_url`, `issuer_email` columns to the
  Tenant model (`app/models/tenant.py`).
- [x] **Step 3** — Alembic migration `alembic/versions/005_badges.py`: create `badge_classes`;
  create partitioned `badge_assertions` (RANGE issued_at) + monthly + DEFAULT partitions;
  partitioned `badge_events` (RANGE created_at) + partitions; indexes (wallet, partial public,
  pg_trgm on name); RLS enable/force + `tenant_isolation` on all three; add tenant issuer columns.
  Reversible `downgrade()`.

### Backend — Business logic (services)
- [x] **Step 4** — `app/services/openbadges.py` (OpenBadgesSerializer): OB 2.0 assertion/class/issuer
  JSON, salted-hash recipient, verification object, revoked/expired handling. (baking deferred)
- [x] **Step 5** — `app/services/badge_event_service.py` (BadgeEventService.record) — minimal append.
- [x] **Step 6** — `app/services/badge_service.py` (BadgeService): create/update/deactivate/get/list
  BadgeClass, attach_image (S3 + malware scan), set_directory_visibility, issuer-profile get/set.
- [x] **Step 7** — `app/services/issuance_service.py` (IssuanceService): issue (linked documents row,
  expiry per Q2=C, audit, anchor, event, notification), bulk_issue (job + enqueue), revoke
  (OB-compliant 200 + reason), get_assertion.
- [x] **Step 8** — Celery task `app/tasks/badge_bulk.py` (`bulk_issue_badges`) + register in celery_app.

### Backend — API layer
- [x] **Step 9** — `app/routers/badges.py` (auth: tenant_admin/issuer): BadgeClass CRUD, image upload,
  issue, bulk-issue, revoke, issuer-profile PUT. RBAC via require_permission; Pydantic request/response
  models; wire into `app/main.py`.
- [x] **Step 10** — `app/routers/public_badges.py` (UNAUTH): hosted assertion JSON, issuer profile,
  verify endpoint (U1 subset). Per-IP throttle dependency + short-TTL cache + `public_badge_service.py`.
  Wire into main + add `/api/v1/public/` to tenant-context middleware public prefixes.
- [x] **Step 11** — RBAC: add badge permissions (`badge:create/read/update/issue/revoke`, etc.) to
  `app/rbac/permissions.py` role map.

### Backend — Tests (example + PBT via Hypothesis)
- [x] **Step 12** — Unit tests: `tests/unit/test_openbadges.py` (11), `test_badge_event_service.py` (2)
  — hashed recipient, expiry, revoke rules, event-type validation. (Service DB-integration tests
  deferred to Build & Test; pure logic covered here.) **18 passed** in the API container.
- [x] **Step 13** — Property tests: `tests/property/test_badge_properties.py` — OB serialize↔parse
  round-trip [PBT-02], raw-identity-never-leaks / revoked-never-valid / expiry-iff-fixed-period /
  single-identifier [PBT-03], domain generators [PBT-07]; strategies added to `tests/property/strategies.py`.

### Frontend (Q3=B)
- [x] **Step 14** — `frontend/src/pages/tenant/BadgeClassesPage.tsx` + modals (create/edit, issue,
  bulk-issue, issuer profile). `data-testid` on interactive elements. Wired route (App.tsx) + nav
  (Layout.tsx). `tsc --noEmit` CLEAN_NO_ERRORS in the frontend container.
- [x] **Step 15** — API client additions `frontend/src/lib/badges.ts` for all badge endpoints.

### Docs & config
- [x] **Step 16** — Config keys in `app/config.py` (PUBLIC_BASE_URL, BADGE_IMAGE_PREFIX,
  OBADGE_CACHE_TTL_SECONDS, PUBLIC_RATE_LIMIT_PER_IP/WINDOW, PRESIGNED_URL_TTL_SECONDS).
- [x] **Step 17** — Code summary doc `aidlc-docs/construction/U1-badge-core/code/summary.md`
  (created vs modified files, story coverage).

## Story Traceability
S1→Steps 6,9,14 · S2→6,9,14 · S3→2,6,9,14 · S4→7,9,14 · S5→7,8,9,14 · S6→7,9,14 · S13→4,10.

## Scope / Estimate
~17 steps; the largest unit. Backend models/migration/services/routers + tests + admin frontend.
Tests are written here; executed in the Build & Test stage.

## Notes
- Partitioned tables use explicit composite PKs (not UUIDPrimaryKeyMixin) — mirror `audit_logs`.
- `badge_events` table created here (brought forward) so U2/U3 can emit/aggregate later.
- Public gateway container wiring (separate deployable) is added in Build & Test / infra step, but the
  `public_badges` router itself is created here (Step 10).
