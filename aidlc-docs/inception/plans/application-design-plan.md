# Application Design Plan — Credly-Style Credentialing

High-level component & service design (not detailed business logic — that's Functional Design per unit).
Please answer the design questions at the bottom, then tell me you're done. I'll resolve ambiguities,
get your approval, then generate the design artifacts.

## Methodology / Execution Checklist (run after approval)
- [ ] components.md — component definitions, responsibilities, interfaces
- [ ] component-methods.md — method signatures + I/O types (no business rules yet)
- [ ] services.md — service definitions, orchestration patterns
- [ ] component-dependency.md — dependency matrix, communication, data flow
- [ ] application-design.md — consolidated design doc
- [ ] Validate completeness against FR-1..FR-7 and stories S1-S15

## Proposed Components (for reference; finalized after approval)
- **BadgeClass model + BadgeService** — template CRUD, image ref, issuer-profile use (U1).
- **BadgeAssertion model + IssuanceService** — issue/bulk/revoke; creates linked `documents` row; hosted OB 2.0 assertion + baked PNG (U1).
- **OpenBadgesSerializer** — build OB 2.0 assertion/issuer JSON; baking; (design VC path) (U1).
- **WalletService** — earner wallet list, hide/delete, public toggle (U2).
- **SharingService** — public badge page data, Open Graph meta, LinkedIn deep-link builder, earner profile, channel-tagged share URLs (U3).
- **DirectoryService** — per-tenant catalog + privacy-gated public earners (U3).
- **AnalyticsService + event counters** — issued/accepted/public/verify counts, channel breakdown (U4).
- **Routers**: badges, wallet, public (assertions/pages/directory), analytics.
- **Frontend pages**: BadgeClasses admin, Analytics, Earner Wallet, Public badge/earner pages, Directory.
- **Reused**: documents/audit/anchoring/encryption/S3, notification, OTP auth, RLS middleware.

---

## Design Questions

## Question 1
Service granularity — how should the new backend logic be organized?

A) Fine-grained services (BadgeService, IssuanceService, WalletService, SharingService, DirectoryService, AnalyticsService) — clear separation, more files

B) Coarse services (one BadgeService covering classes+issuance+wallet; one PublicService covering sharing+directory; one AnalyticsService)

C) Recommend for me based on the existing codebase conventions

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2
Hosted assertion & issuer-profile endpoints — where should they live?

A) New public router `public_badges` (unauthenticated) for assertion JSON, issuer profile, public pages, directory — separate from authenticated admin/issuer routers

B) Fold public endpoints into the existing verification router

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 3
Analytics counting mechanism (drives component design)?

A) Increment counter rows/events synchronously in the same transaction as the action (simple, exact)

B) Emit events and aggregate via a Celery periodic task (scales better at 10M+, eventually-consistent)

C) Hybrid — synchronous counters for issue/accept/publish; async aggregation for high-volume verify/view

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 4
Frontend scope for this feature?

A) Full — admin BadgeClass management, analytics dashboard, earner wallet, public badge/earner pages, directory

B) Admin + earner wallet only; public pages are server-rendered minimal HTML (no SPA)

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5
Baking (embedding OB metadata into PNG) — implementation approach?

A) Implement PNG iTXt-chunk baking now (full OB 2.0 baked-badge support)

B) Defer baking; serve hosted assertions + plain image now, add baking in a later increment

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: 
B