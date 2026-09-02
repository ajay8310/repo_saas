# Application Design (Consolidated) — Credly-Style Credentialing

Consolidates: components.md, component-methods.md, services.md, component-dependency.md.

## Design Decisions (from application-design-plan.md)
- **Q1=A** Fine-grained services (6): BadgeService, IssuanceService, WalletService, SharingService, DirectoryService, AnalyticsService (+ OpenBadgesSerializer helper, BadgeEventService helper).
- **Q2=A** Dedicated unauthenticated `public_badges` router for assertions/issuer profile/public pages/directory/verify.
- **Q3=B** Async analytics: append `BadgeEvent`, aggregate via Celery beat into `BadgeAnalyticsDaily`.
- **Q4=A** Full frontend (admin BadgeClasses, analytics, earner wallet, public pages, directory).
- **Q5=B** Baking deferred; hosted OB 2.0 assertions are the verifiable artifact now. FR-2.3 → future increment.

## New Data Models
- `badge_classes` — template (RLS).
- `badge_assertions` — issued instance, linked to `documents.id` (hybrid), RLS.
- `badge_events` — append-only analytics event stream (RLS).
- `badge_analytics_daily` — aggregated rollup (RLS).

## New Services
BadgeService · IssuanceService · OpenBadgesSerializer · WalletService · SharingService ·
DirectoryService · AnalyticsService · BadgeEventService (see component-methods.md for signatures).

## New Routers
- `badges` (auth) · `wallet` (auth/earner) · `public_badges` (unauth) · `badge_analytics` (auth).

## New Celery Tasks
- `aggregate_badge_analytics` (beat) · `bulk_issue_badges`.

## New Frontend Pages
- BadgeClassesPage, BadgeAnalyticsPage, WalletPage, Public badge/earner pages, Directory.

## Reuse (no change)
documents/audit/anchoring/encryption/S3, notification, OTP auth, RLS middleware, rate limiter, malware scanner.

## Requirement / Story Coverage
- FR-1 → BadgeClass/BadgeAssertion models, BadgeService, IssuanceService (S1, S4).
- FR-2 → IssuanceService + OpenBadgesSerializer + issuer profile; FR-2.3 baking deferred (S3, S4, S5, S6, S13).
- FR-3 → WalletService, private-by-default (S7, S8, S10).
- FR-4 → SharingService (S10, S11, S15).
- FR-5 → DirectoryService (S12, S14).
- FR-6 → BadgeEvent + aggregator + AnalyticsService (S9).
- FR-7 → public verify via public_badges + OpenBadgesSerializer (S6, S13).

## Units Mapping (for Units Generation)
- **U1 Badge Core**: models (badge_classes, badge_assertions), migration+RLS, BadgeService, IssuanceService, OpenBadgesSerializer, badges router, issuer profile, revocation, public assertion/verify endpoints.
- **U2 Wallet**: WalletService, wallet router, earner UI, privacy toggle, hide/delete.
- **U3 Sharing & Directory**: SharingService, DirectoryService, public router pages, OG meta, LinkedIn deep-link, earner profile, directory UI.
- **U4 Analytics**: badge_events, badge_analytics_daily, BadgeEventService, aggregate task, AnalyticsService, analytics router + dashboard UI.

## Deferred / Out of Scope (this build)
- PNG baking (FR-2.3), OB 3.0/W3C VC signing, LinkedIn API (deep-link only), LMS/HR connectors,
  endorsements — all documented seams, not implemented now.

## Resiliency & PBT hooks (extensions)
- Resiliency: Backup&Restore (existing PG backups cover new tables; S3 versioning covers images);
  single-region multi-zone; lightweight IR proposed in NFR Design.
- PBT (enforced): OB serialize↔parse round-trip, private-by-default invariant, revoked-never-valid,
  share-URL channel preservation, tenant isolation — identified now, detailed in Functional Design (PBT-01).
