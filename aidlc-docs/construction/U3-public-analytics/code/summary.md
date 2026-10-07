# U3 Public Directory + Analytics — Code Generation Summary

Final Credly-style unit: public sharing (S12), public directory (S14), and issuer
analytics (S15) backed by an async daily rollup.

## Created files
- `alembic/versions/007_badge_analytics.py` — `badge_analytics_daily` rollup (RLS, partial unique
  indexes for per-class and tenant-wide rows). Reversible.
- `app/services/identity_masking.py` — shared `mask_identity` (Q5=A, BR-P2).
- `app/services/share_service.py` — share URL + channel event, LinkedIn deep link, Open Graph meta;
  non-public/revoked → None → 404.
- `app/services/directory_service.py` — catalog, public earners, earner profile; public-only filters;
  keyset pagination (BR-D3).
- `app/services/analytics_service.py` — overview / by-badge / ranking read models over the rollup.
- `app/services/analytics_aggregator.py` — idempotent upsert aggregation; tenant-wide = sum of
  per-class (BR-A3); Redis watermark.
- `app/tasks/badge_analytics.py` — `aggregate_badge_analytics` Celery task.
- `app/routers/analytics.py` — authenticated analytics endpoints.
- `tests/unit/test_share_service.py` (5), `tests/unit/test_identity_masking.py` (4),
  `tests/property/test_analytics_properties.py` (4).
- `frontend/src/lib/analytics.ts`, `frontend/src/lib/directory.ts`.
- `frontend/src/pages/tenant/BadgeAnalyticsPage.tsx`, `frontend/src/pages/public/DirectoryPage.tsx`.

## Modified files
- `app/models/badge.py` — `BadgeAnalyticsDaily` model; `app/models/__init__.py` — re-export.
- `app/routers/public_badges.py` — directory, earners, earner profile, share routes.
- `app/tasks/celery_app.py` — include + beat schedule (120s, Q6=A).
- `app/rbac/permissions.py` — `badge:analytics`.
- `app/config.py` — analytics interval + directory page sizes.
- `app/main.py` — wire analytics router.
- `tests/property/strategies.py` — certificate/signing + (reused) badge strategies.
- `frontend/src/App.tsx` — public `/directory` route + issuer `/badge-analytics` route.
- `frontend/src/components/Layout.tsx` — Badge Analytics nav.

## Verification performed
- App import in API container: RC=0.
- `pytest` U3 unit + property: **13 passed** (5 share + 4 masking + 4 property).
- Frontend `tsc --noEmit`: CLEAN_NO_ERRORS.
- Migration 007 upgrade→downgrade→upgrade reversible (now 007 head).

## Decisions honoured
Q5=A masked identity · Q6=A async ~120s idempotent aggregation · Q7=A uniform 404 for non-public ·
keyset pagination · per-IP throttle + short-TTL cache reused from U1.

## Notes
- Aggregation idempotence proven by a pure reference fold in property tests
  (`aggregate(aggregate(x))==aggregate(x)`, tenant-wide=sum); the DB upsert path uses two partial
  unique indexes because NULL class_id can't share a plain UNIQUE with per-class rows.
- Analytics aggregator enumerates tenants from the (non-RLS) `tenants` table and scopes each via
  `set_tenant_context` — no RLS-bypass toggle, works with a least-privilege DB role.
- LinkedIn/social sharing is deep-link only (no external API/account), per BR-P4.
