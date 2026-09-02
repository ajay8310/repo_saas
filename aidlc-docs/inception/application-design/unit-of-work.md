# Units of Work — Credly-Style Credentialing

**Context**: Brownfield monolith (single FastAPI service). Units are **logical modules / build
increments**, not separately deployable services. Decomposition per Q1=B (merge public + analytics).

## Construction approach (user overrides)
- **Q2=B**: Design ALL units first (Functional Design → NFR Requirements → NFR Design → Infrastructure
  Design covering all 3 units), THEN Code Generation for all units. This deviates from the AI-DLC
  default per-unit design→code loop and is an approved user override.
- **Q3=B**: During Code Generation, each unit is built full-stack (backend + frontend) in one pass.

## Units

### U1 — Badge Core
- **Responsibilities**:
  - Models: `badge_classes`, `badge_assertions` (+ Alembic migration, RLS policies).
  - Services: `BadgeService` (template CRUD, image, directory-visibility flag, issuer profile),
    `IssuanceService` (single + **bulk** issue [Q4=A], revoke; linked `documents` row; audit; anchor;
    notification event), `OpenBadgesSerializer` (OB 2.0 assertion/class/issuer JSON, verification).
  - Router: `badges` (auth) + issuer-profile endpoint.
  - Public: hosted assertion JSON, issuer profile, verify endpoint (subset of `public_badges` router
    needed for verification of issued badges).
  - Celery: `bulk_issue_badges`.
  - Frontend: BadgeClasses admin page (create/edit/image/issue/bulk/revoke).
- **Module layout**: `app/models/badge.py`, `app/services/badge_service.py`,
  `app/services/issuance_service.py`, `app/services/openbadges.py`, `app/routers/badges.py`,
  `app/routers/public_badges.py` (verify subset), `app/tasks/badge_bulk.py`,
  `frontend/src/pages/tenant/BadgeClassesPage.tsx`.

### U2 — Wallet
- **Responsibilities**: `WalletService` (list, hide/delete, public opt-in — private-by-default);
  `wallet` router (earner/OTP); earner wallet frontend with per-badge public toggle + share entry.
- **Module layout**: `app/services/wallet_service.py`, `app/routers/wallet.py`,
  `frontend/src/pages/earner/WalletPage.tsx`.

### U3 — Public & Analytics (merged Sharing + Directory + Analytics)
- **Responsibilities**:
  - Sharing: `SharingService` (public badge page data, Open Graph meta, LinkedIn deep-link, earner
    public profile, channel-tagged share URL).
  - Directory: `DirectoryService` (per-tenant catalog + privacy-gated public earners, keyset pagination).
  - Analytics: `badge_events`, `badge_analytics_daily` models; `BadgeEventService` (append);
    `aggregate_badge_analytics` Celery beat task; `AnalyticsService` (read rollups).
  - Router: extend `public_badges` (public pages, directory) + `badge_analytics` (auth).
  - Frontend: public badge page, earner profile, directory, BadgeAnalytics dashboard.
- **Module layout**: `app/services/sharing_service.py`, `app/services/directory_service.py`,
  `app/services/analytics_service.py`, `app/services/badge_event_service.py`,
  `app/models/badge_event.py`, `app/tasks/badge_analytics.py`, extend `app/routers/public_badges.py`,
  `app/routers/badge_analytics.py`, plus public + analytics frontend pages.

## Notes
- Event emission (`BadgeEventService.record`) is introduced in U3 but **called from** U1 (issued) and
  U2 (published). To avoid a backward dependency during design-all-then-code, U1/U2 will emit events
  through a thin, stable `BadgeEventService` interface defined in U3's design but implemented such that
  U1/U2 can call it; if U3 code lands last, U1/U2 issue/publish still function and events accrue once
  U3's table/service exist. Build order (below) sequences U3's event model early to avoid this.
