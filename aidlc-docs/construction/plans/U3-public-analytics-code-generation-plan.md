# U3 — Public Directory + Analytics — Code Generation Plan

**Single source of truth.** Full-stack. Brownfield: modify existing files in place. Application code at
workspace root. Final Credly-style unit (U3 = merged public directory + analytics, per Q1=B earlier).

## Scope / Stories
- **S12** sharing (LinkedIn/social deep links + share event + Open Graph meta).
- **S14** public directory (catalog of directory-visible classes; public earners per class; keyset paging).
- **S15** issuer analytics dashboard (issued/accepted/published/shared/verified/viewed; per-badge + rank;
  channel breakdown) backed by an async daily rollup.
- Public earner profile (masked identity) listing an earner's public badges.

## Already built (U1 — reuse, do not duplicate)
`app/routers/public_badges.py` (+ `_throttle`, `/public/badges` prefix in middleware),
`app/services/public_badge_service.py` (hosted assertion/class/issuer, short-TTL Redis cache),
`BadgeEvent` + `BadgeEventService` (append-only events: issued/accepted/published/shared/verified/
viewed/revoked), `app/services/openbadges.py`.

## Decisions baked in
Q5=A masked earner identity (never raw email) · Q6=A async aggregation ~2 min, idempotent ·
Q7=A uniform 404 for non-public · keyset pagination (BR-D3) · per-IP throttle on public routes ·
short-TTL cache. No new auth surface for public reads.

## Steps

### Backend — Schema & model
- [ ] **Step 1** — Migration `007_badge_analytics.py`: create `badge_analytics_daily`
  (id, tenant_id, day, badge_class_id NULL, issued/accepted/published/shared/verified/viewed counts,
  channel_breakdown JSONB, updated_at; UNIQUE(tenant_id, day, badge_class_id)); RLS via `_apply_rls`;
  index (tenant_id, day). Add `BadgeAnalyticsDaily` model + register in `app/models/__init__.py`.
  Reversible.

### Backend — Services
- [ ] **Step 2** — `app/services/share_service.py` (`ShareService`): `build_share_url(assertion_id,
  channel)` → tagged public URL + record `shared` event with channel (BR-P5); `linkedin_url` /
  `open_graph_meta` built from class/assertion fields only (BR-P3/P4); refuses non-public/revoked
  (BR-P6) → None → 404.
- [ ] **Step 3** — `app/services/directory_service.py` (`DirectoryService`): `list_classes(tenant_id,
  cursor, limit)` directory_visible only (BR-D1, keyset); `list_public_earners(tenant_id, class_id,
  cursor, limit)` public assertions only, masked names (BR-D2); `earner_profile(tenant_id,
  beneficiary_id)` masked name + that earner's public badges. All reads filter `public=true` /
  `directory_visible=true` (BR-P1).
- [ ] **Step 4** — `app/services/analytics_service.py` (`AnalyticsService`): read models over
  `badge_analytics_daily` — `overview(tenant_id, from, to)`, `by_badge(tenant_id, class_id, range)`,
  `ranking(tenant_id, metric, range)`; tenant-scoped (BR-A4). Masking helper `mask_identity` shared
  with public_badge_service (extract to one place).
- [ ] **Step 5** — `app/services/analytics_aggregator.py` (`AnalyticsAggregator.run(tenant_id=None)`):
  read `badge_events` since a watermark, group by (tenant, day, class, type), upsert into
  `badge_analytics_daily` on the UNIQUE key, accumulate `channel_breakdown` for shares; also upsert
  the tenant-wide (class_id=NULL) row = sum per metric (BR-A3). Idempotent (BR-A2). Watermark stored
  in Redis per tenant.

### Backend — Tasks
- [ ] **Step 6** — `app/tasks/badge_analytics.py` (`aggregate_badge_analytics` Celery task) +
  register in `celery_app.py` include list + beat schedule every 120s (Q6=A).

### Backend — API
- [ ] **Step 7** — Extend `app/routers/public_badges.py` (UNAUTH): `GET /public/badges/directory`
  (classes), `GET /public/badges/directory/{class_id}/earners`, `GET /public/badges/earners/
  {beneficiary_ref}` (profile), `GET /public/badges/assertions/{id}/share?channel=` (share URL +
  OG meta). Keyset `cursor`/`limit`; per-IP throttle; uniform 404.
- [ ] **Step 8** — `app/routers/analytics.py` (AUTH, issuer/admin): `GET /badge-analytics/overview`,
  `/badge-analytics/by-badge/{class_id}`, `/badge-analytics/ranking`. RBAC `badge:analytics`. Wire
  into `app/main.py`.
- [ ] **Step 9** — RBAC: add `badge:analytics` to issuer/tenant_admin/super_admin in `permissions.py`.

### Backend — Config & tests
- [ ] **Step 10** — `app/config.py`: `analytics_aggregation_interval_seconds=120`,
  `directory_page_size_default`, `directory_page_size_max`.
- [ ] **Step 11** — Unit tests: `tests/unit/test_share_service.py` (share URL + channel, non-public→
  None, OG meta), `tests/unit/test_analytics_aggregator.py` (idempotent upsert, tenant-wide=sum).
- [ ] **Step 12** — Property tests `tests/property/test_analytics_properties.py`:
  [PBT-02] share-URL round-trip, [PBT-03] only public in views / tenant-wide=sum invariant,
  [PBT-04] aggregate idempotence `aggregate(aggregate(x))==aggregate(x)`. Strategies to strategies.py.

### Frontend
- [ ] **Step 13** — `frontend/src/lib/directory.ts` + `analytics.ts`: public directory + analytics
  API clients; share-URL/LinkedIn helpers.
- [ ] **Step 14** — Public pages (unauth): `frontend/src/pages/public/DirectoryPage.tsx` (catalog +
  earners, keyset “load more”), extend the existing public verify/badge view with share buttons
  (LinkedIn/copy) + OG tags. Routes in `App.tsx` (public, no ProtectedRoute).
- [ ] **Step 15** — `frontend/src/pages/tenant/BadgeAnalyticsPage.tsx` (issuer dashboard: metric
  cards, per-badge table, ranking, channel breakdown). Route + nav (issuing roles). `data-testid`s.

### Docs
- [ ] **Step 16** — Code summary `aidlc-docs/construction/U3-public-analytics/code/summary.md`.

## Verification
Build/import in API container; `alembic upgrade head` then `downgrade -1`; run new unit + property
tests; frontend `tsc`; restart api; confirm new routes in live OpenAPI. Clean up temp files.

## Notes
- Masking (`mask_identity`) is currently inline in CertificateService/public paths; consolidate into
  one helper (e.g. `app/services/identity_masking.py`) and reuse (Q5=A, BR-P2).
- Aggregation watermark in Redis keeps re-runs cheap and idempotent; a cold Redis just reprocesses a
  bounded window (safe — upsert).
- LinkedIn/social sharing is deep-link only (no external API/account), per BR-P4.
