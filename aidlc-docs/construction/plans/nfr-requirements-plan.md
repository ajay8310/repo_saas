# NFR Requirements Plan — All Units (U1, U2, U3)

Covers non-functional requirements + tech-stack decisions for the badge feature. Much is already
decided (scale 10M+/tenant, DR=Backup&Restore, single-region multi-zone, PBT enabled). This stage
confirms performance targets, tech choices, and records PBT-09 framework selection.

Answer the questions, then tell me you're done.

## Known / inherited (not re-asked)
- **Tech stack**: reuse existing — Python 3.12/FastAPI, SQLAlchemy async/PostgreSQL 16 (RLS), Redis 7,
  Celery, boto3 S3/KMS/SES/SNS, React/Vite/TS frontend. New badge feature adds NO new frameworks.
- **PBT framework (PBT-09)**: **Hypothesis** (already in dev deps) — will be recorded in tech-stack-decisions.
- **Resiliency**: DR=Backup&Restore (RTO/RPO hours), single-region multi-zone, incident response =
  propose lightweight (addressed in NFR Design).
- **Security extension**: disabled (reuse existing JWT/RBAC/RLS/encryption for authed endpoints).

## Methodology / Execution Checklist (run after approval)
- [x] nfr-requirements.md (scalability, performance, availability, security-reuse, reliability, maintainability, usability)
- [x] tech-stack-decisions.md (confirm reuse + Hypothesis for PBT + any new libs like PNG/QR already present)

---

## Questions

## Question 1  (performance targets)
Confirm performance targets for the new endpoints (from requirements NFR-1):

A) As stated: hosted assertion fetch p95 < 500ms; wallet/directory list p95 < 1s at target scale

B) Relax (this is value-add, not core): p95 < 1.5s across new read endpoints

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 2  (scale realization for 10M+ assertions)
How to physically handle 10M+ assertions/tenant?

A) Indexes + keyset pagination now; defer table partitioning until data volume warrants (documented trigger)

B) Partition `badge_assertions` from the start (e.g., by tenant hash or issued_at range)

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: B

## Question 3  (public endpoint abuse protection)
Unauthenticated public endpoints (assertions, pages, directory) — protection?

A) Reuse existing per-tenant rate limiter + add per-IP throttling for public routes

B) Reuse existing rate limiter only

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 4  (caching for public/verify reads)
Caching strategy for hot public reads (assertion JSON, public pages)?

A) Short-TTL cache (e.g., 60s) in Redis for assertion JSON + directory pages; invalidate on revoke/unpublish

B) No caching now (rely on DB indexes); add later if needed

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A

## Question 5  (accessibility for public pages / dashboard)
Accessibility requirement level for new UI?

A) WCAG 2.1 AA target for public pages + admin dashboard (semantic HTML, alt text, contrast, keyboard nav)

B) Best-effort accessibility, no formal target

X) Other (please describe after [Answer]: tag below)

[Answer]: A
