# NFR Requirements — Badge Feature (U1, U2, U3)

Cross-unit non-functional requirements. Answers: Q1=A targets, Q2=B partition from start,
Q3=A rate-limit + per-IP, Q4=A short-TTL cache, Q5=A WCAG 2.1 AA.

## Scalability
- **SCALE-1**: Support **10M+ `badge_assertions` per tenant**.
- **SCALE-2** (Q2=B): `badge_assertions` is **partitioned from the start**. Partition strategy to be
  finalized in NFR Design; candidate: RANGE by `issued_at` (monthly), mirroring the existing
  `audit_logs` partitioning pattern, with a composite PK `(id, issued_at)`. `badge_events` likewise
  partitioned by `created_at`. Trade-off vs HASH-by-tenant to be decided in NFR Design.
- **SCALE-3**: All list endpoints (wallet, directory, public earners) use **keyset/seek pagination**
  (cursor), never OFFSET, to stay performant at scale.
- **SCALE-4**: Indexes on `(tenant_id, badge_class_id)`, `(tenant_id, beneficiary_id)`,
  `(tenant_id, public)` partial index for public queries, and pg_trgm GIN for catalog search.

## Performance (Q1=A)
- **PERF-1**: Hosted assertion JSON fetch **p95 < 500ms**.
- **PERF-2**: Wallet and directory list **p95 < 1s** at target scale.
- **PERF-3**: Public verify **p95 < 500ms**.
- **PERF-4** (Q4=A): Short-TTL **Redis cache (~60s)** for hosted assertion JSON and directory pages;
  **invalidate on revoke/unpublish/edit** to avoid stale public data.

## Availability & Resiliency (from requirements; Resiliency extension)
- **AVAIL-1** (RESILIENCY-02): DR = **Backup & Restore**, RTO/RPO in hours. New tables covered by the
  existing automated PostgreSQL backups; badge images covered by S3 versioning.
- **AVAIL-2** (RESILIENCY-08): **Single-region, multi-zone** (inherits platform topology).
- **AVAIL-3** (RESILIENCY-15): **Propose a lightweight incident-response + COE** process (detailed in
  NFR Design) since none exists; wire new-feature alerts into it.
- **AVAIL-4** (RESILIENCY-01): Badge feature criticality = **Medium** (value-add, not core issuance).
- **AVAIL-5** (RESILIENCY-06): New routers expose/participate in the existing health-check surface.

## Security (Security extension disabled — reuse only)
- **SEC-1**: Authenticated endpoints (badges, wallet, analytics) reuse existing JWT + RBAC + RLS.
- **SEC-2** (Q3=A): Public unauthenticated endpoints get **per-IP throttling** in addition to the
  existing per-tenant rate limiter, to mitigate scraping/abuse.
- **SEC-3**: Public surfaces expose only `public=true` / `directory_visible=true` data; earner
  identity is masked (never raw email). Recipient identity in OB assertion is salted-hashed.
- **SEC-4**: Image uploads are malware-scanned (reuse) and mime/size-validated.

## Reliability
- **REL-1**: Analytics aggregation is **idempotent** (upsert + watermark) — safe to re-run; a missed
  run self-heals on the next pass.
- **REL-2**: Bulk issuance processes rows independently; partial success reported; no partial writes
  per row (savepoint).
- **REL-3**: Revocation and unpublish invalidate any cached public representation.

## Maintainability / Testability (PBT extension)
- **MAINT-1**: Follow existing steering conventions (async, `Mapped[]` models, service layer, DI).
- **MAINT-2** (PBT): Property-based tests via **Hypothesis** for identified properties (round-trip,
  private-by-default, revoked-never-valid, only-public-listed, aggregation idempotence/consistency),
  complemented by example-based tests for critical paths.

## Usability / Accessibility (Q5=A)
- **UX-1**: New UI (public badge page, earner profile, directory, admin dashboard) targets **WCAG 2.1
  AA**: semantic HTML, image alt text (badge art), sufficient color contrast, keyboard navigation,
  focus states, and accessible form labels. Note: full WCAG validation requires manual testing with
  assistive technologies and expert review — this sets the target, not a certification.
