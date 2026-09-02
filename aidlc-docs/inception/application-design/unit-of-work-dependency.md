# Unit Dependency Matrix — Credly-Style Credentialing

## Dependencies

| Unit | Depends on | Reason |
|---|---|---|
| U1 Badge Core | (existing platform: documents, audit, anchoring, encryption/S3, notification, RLS) | issuance reuses core storage/audit; foundation for all badges |
| U2 Wallet | U1 (badge_assertions), existing OTP auth | wallet lists/toggles assertions created by U1 |
| U3 Public & Analytics | U1 (assertions, serializer), U2 (public flag set in wallet) | public pages/directory expose opted-public assertions; analytics aggregates events emitted by U1/U2/U3 |

## Event-emission cross-cut
- `BadgeEventService` + `badge_events` table are owned by **U3** but **called by U1** (issued) and
  **U2** (published). To keep U1/U2 independently functional, the `badge_events` table + a minimal
  `BadgeEventService.record` are scheduled **early** in the build order.

## Build Order (Code Generation, after all-units design — Q2=B)
1. **U1 Badge Core** — models + migration (badge_classes, badge_assertions) + `badge_events` table
   (bring forward from U3 so event emission works), BadgeService, IssuanceService (single+bulk),
   OpenBadgesSerializer, minimal BadgeEventService.record, badges router, public verify subset,
   BadgeClasses frontend.
2. **U2 Wallet** — WalletService, wallet router, earner wallet frontend (emits "published" events).
3. **U3 Public & Analytics** — SharingService, DirectoryService, `badge_analytics_daily`,
   `aggregate_badge_analytics` task, AnalyticsService, public pages + directory + analytics router,
   public/analytics frontend.

## Rationale
- Sequential, dependency-respecting order. Bringing the `badge_events` table forward into U1 removes
  the only backward dependency, so U1 and U2 record events from day one and U3 simply adds aggregation
  + read + public surfaces.

## Parallelization
- With Q2=B (design all first), the **design** stages cover all 3 units together. **Code** is
  sequential U1 → U2 → U3. Within a unit (Q3=B), backend + frontend are built together.
