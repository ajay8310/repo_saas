# U1 Badge Core — Code Generation Summary

Brownfield generation for the Credly-style badge feature. All application code is
at the workspace root; this file is the documentation-only summary.

## Created files
- `app/models/badge.py` — `BadgeClass`, `BadgeAssertion` (composite PK `(id, issued_at)`,
  UNIQUE(id)), `BadgeEvent` (composite PK `(id, created_at)`).
- `alembic/versions/005_badges.py` — creates the three tables, RANGE partitions
  (monthly + DEFAULT), indexes (wallet, partial `WHERE public=true`, pg_trgm on name,
  UNIQUE on assertion id), RLS on all three, and tenant issuer columns. Reversible.
- `app/services/openbadges.py` — `OpenBadgesSerializer` (OB 2.0 assertion/class/issuer JSON,
  salted-hash recipient identity, hosted verification object, revoked/expiry handling).
- `app/services/badge_event_service.py` — `BadgeEventService.record` (append-only analytics).
- `app/services/badge_service.py` — `BadgeService` (BadgeClass CRUD, image upload w/ malware scan,
  presigned image URL, directory visibility, issuer profile get/set).
- `app/services/issuance_service.py` — `IssuanceService` (issue, bulk enqueue, OB-compliant revoke,
  reads; assertion id == credential id; expiry per Q2=C).
- `app/services/public_badge_service.py` — `PublicBadgeService` (unauth hosted-artifact resolution,
  public-only filtering, short-TTL Redis cache, verification event).
- `app/tasks/badge_bulk.py` — `bulk_issue_badges` Celery task (independent per-recipient issuance).
- `app/routers/badges.py` — authenticated tenant-admin/issuer API (classes, image, issue, bulk,
  revoke, visibility, issuer profile).
- `app/routers/public_badges.py` — unauthenticated hosted assertion/class/issuer + per-IP throttle.
- `tests/unit/test_openbadges.py`, `tests/unit/test_badge_event_service.py` — 13 unit tests.
- `tests/property/test_badge_properties.py` — 5 Hypothesis properties (PBT-02/03/07).
- `frontend/src/lib/badges.ts` — badge API client + types.
- `frontend/src/pages/tenant/BadgeClassesPage.tsx` — admin Badges page + modals (data-testid'd).

## Modified files
- `app/models/tenant.py` — added `issuer_name`, `issuer_url`, `issuer_email`.
- `app/models/__init__.py` — re-export badge models.
- `app/rbac/permissions.py` — badge permissions for super_admin / tenant_admin / issuer.
- `app/tasks/celery_app.py` — registered `app.tasks.badge_bulk` in the include list.
- `app/config.py` — badge config keys (public_base_url, badge_image_prefix, obadge_cache_ttl_seconds,
  presigned_url_ttl_seconds, public_rate_limit_per_ip/window).
- `app/main.py` — imported + wired `badges` and `public_badges` routers.
- `app/middleware/tenant_context.py` — added `/api/v1/public/` to public prefixes.
- `tests/property/strategies.py` — badge Hypothesis strategies.
- `frontend/src/App.tsx`, `frontend/src/components/Layout.tsx` — route + nav for Badges.

## Verification performed
- Full app import inside the API container: `IMPORTS_OK`.
- `pytest tests/unit/test_openbadges.py tests/unit/test_badge_event_service.py
  tests/property/test_badge_properties.py`: **18 passed**.
- Frontend `tsc --noEmit`: **CLEAN_NO_ERRORS**.
- Migration `005_badges.py` NOT yet applied to the DB — deferred to the Build & Test stage
  (with `alembic upgrade head` then `downgrade -1` reversibility check).

## Story coverage
S1 (create/edit class), S2 (image), S3 (issuer profile), S4 (issue), S5 (bulk issue),
S6 (revoke), S13 (hosted assertion + verify) — all implemented.

## Deferred (by approved decision)
- Badge baking into PNG/SVG (Q5=B) — hosted assertion URL is the U1 verifiable artifact.
- Service-level DB-integration tests — Build & Test stage (require live Postgres + RLS).
- Public-gateway container wiring (Q3=B infra) — Build & Test / infra step.
