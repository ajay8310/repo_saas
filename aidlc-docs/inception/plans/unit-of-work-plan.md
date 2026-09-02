# Unit of Work Plan — Credly-Style Credentialing

Decompose the feature into units of work (logical modules within the existing monolith service — this
is NOT a new microservice). Application Design proposed U1-U4. Please answer the questions below,
then tell me you're done. I'll get your approval, then generate the unit artifacts.

## Context
- This is a **brownfield monolith** (single FastAPI service). Units = logical modules/build increments,
  NOT separately deployable services.
- Proposed units (from application-design.md):
  - **U1 Badge Core** — models (badge_classes, badge_assertions), migration+RLS, BadgeService,
    IssuanceService, OpenBadgesSerializer, badges router, issuer profile, revocation, public
    assertion/verify endpoints.
  - **U2 Wallet** — WalletService, wallet router, earner UI, privacy toggle, hide/delete.
  - **U3 Sharing & Directory** — SharingService, DirectoryService, public pages, OG meta, LinkedIn
    deep-link, earner profile, directory UI.
  - **U4 Analytics** — badge_events, badge_analytics_daily, BadgeEventService, aggregate task,
    AnalyticsService, analytics router + dashboard UI.

## Methodology / Execution Checklist (run after approval)
- [x] Generate `unit-of-work.md` (unit definitions, responsibilities, module layout)
- [x] Generate `unit-of-work-dependency.md` (dependency matrix + build order)
- [x] Generate `unit-of-work-story-map.md` (stories S1-S15 → units)
- [x] Validate boundaries; ensure all stories assigned; confirm dependency order

## Decisions (answered)
- Q1=B: merge U3+U4 → 3 units total.
- Q2=B: design ALL units first, then code ALL units (override of default per-unit loop).
- Q3=B: full-stack per unit during code generation.
- Q4=A: bulk issue in U1.

---

## Questions

## Question 1
Keep the 4-unit decomposition (U1-U4), or adjust?

A) Keep U1-U4 as proposed (Badge Core, Wallet, Sharing & Directory, Analytics)

B) Merge U3 + U4 (public + analytics together)

C) Split U1 (models/migration as its own unit before services)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 2
Build/approval cadence across units?

A) One unit at a time, each fully designed + coded + tested + approved before the next (safest, sequential)

B) Design all units first, then code all units

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 3
Within a unit, how should backend vs frontend be sequenced?

A) Backend (models/services/routers/tests) first, then frontend for that unit

B) Full-stack per unit in one pass (backend + frontend together)

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 4
Story S5 (bulk issue) and the bulk Celery task — which unit?

A) Keep in U1 (Badge Core) alongside single issuance

B) Separate into its own small unit after U1

X) Other (please describe after [Answer]: tag below)

[Answer]: A
