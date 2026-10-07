# NFR Design Patterns — Badge Feature (U1, U2, U3)

Decisions (delegated to AI judgment): Q1=A RANGE-by-issued_at partition; Q2=A composite PK + unique id;
Q3=A targeted cache invalidation; Q4=A lightweight IR+COE; Q5=A DR checklist now/execute in Operations.

## 1. Partitioning (SCALE-2)
- **`badge_assertions`**: `PARTITION BY RANGE (issued_at)`, monthly partitions, plus a `DEFAULT`
  partition catch-all — mirroring the existing `audit_logs` design.
  - **Composite PK `(id, issued_at)`** (partition column must be in the PK).
  - **UNIQUE index on `id` alone** so `id == credential_id == documents.id` remains a single public
    identifier for hosted URLs and the documents FK link.
  - RLS `tenant_isolation` policy applied to the parent (partitions inherit).
  - Monthly partitions pre-created via migration; a maintenance note documents adding future months
    (same operational pattern as audit_logs).
- **`badge_events`**: `PARTITION BY RANGE (created_at)`, monthly, composite PK `(id, created_at)`.
- **`badge_analytics_daily`**: not partitioned (small, one row per tenant/day/class); UNIQUE
  `(tenant_id, day, badge_class_id)`.
- **`badge_classes`**: not partitioned (bounded count per tenant).

## 2. Pagination (SCALE-3)
- **Keyset/seek** everywhere: wallet, directory catalog, public-earner lists. Cursor encodes
  `(issued_at, id)` or `(name, id)` as appropriate; no OFFSET.

## 3. Indexing (SCALE-4, PERF)
- `badge_assertions`: index `(tenant_id, beneficiary_id, issued_at desc)` (wallet),
  partial index `WHERE public = true` on `(tenant_id, badge_class_id, issued_at desc)` (public/directory),
  UNIQUE `(id)`.
- `badge_classes`: index `(tenant_id, status)`, partial `WHERE directory_visible = true`,
  pg_trgm GIN on `name` (+ tags) for catalog search.
- `badge_events`: index `(tenant_id, created_at)`, `(assertion_id)`.

## 4. Caching + invalidation (PERF-4, Q3=A/Q4)
- **Redis short-TTL (~60s)** for: hosted assertion JSON (`obadge:assn:{credential_id}`), public badge
  page payload (`obadge:page:{credential_id}`), directory page slices (`obadge:dir:{tenant}:{cursor}`).
- **Targeted invalidation** (Q3=A): on revoke, unpublish, or BadgeClass edit, delete the exact keys
  for the affected assertion/class; directory slices for the tenant are versioned by a
  `obadge:dir:ver:{tenant}` counter bumped on catalog changes (avoids scanning keys).
- Correctness rule: revoked/unpublished data must never be served stale beyond the invalidation.

## 5. Public-endpoint throttling (SEC-2, Q3)
- Reuse the per-tenant sliding-window limiter for authed routes.
- Add a **per-IP token bucket** (Redis) for the `public_badges` routes (assertion JSON, pages,
  directory, verify). Configurable limit; returns 429 + Retry-After (consistent with existing pattern).

## 6. Idempotent analytics aggregation (REL-1)
- `aggregate_badge_analytics` (Celery beat, ~2 min): process events since a stored **watermark**
  (last `created_at`/id), UPSERT into `badge_analytics_daily` by the UNIQUE key. Re-running over the
  same window yields identical counts (idempotent) — satisfies PBT-04.
- Maintain both per-class rows and a tenant-wide (`badge_class_id = null`) row; the latter equals the
  sum of per-class rows (PBT-03 rollup consistency).

## 7. Resilience patterns
- **Reuse timeouts/circuit patterns** already in the platform for S3/KMS/SES calls (issuance path).
- **Graceful degradation**: if the analytics cache/rollup is stale or the aggregator is behind, reads
  return last-known rollup (dashboard tolerates minor lag); core issuance/verify never depend on it.
- **Backup & Restore (AVAIL-1)**: new tables covered by existing automated PG backups; badge images by
  S3 versioning. No new cross-region infra (single-region MZ, AVAIL-2).

## 8. Incident Response (RESILIENCY-15, Q4=A) — proposed lightweight process
- **Detect**: feature alerts (aggregation failures, elevated 5xx on badge routes, cache errors) route
  to the platform's existing alert channel.
- **Triage → Mitigate**: on-call assesses; mitigations include disabling the aggregator (analytics
  degrade gracefully), flushing/bypassing cache, or feature-flagging new endpoints.
- **COE**: a short Correction-of-Errors note (impact, root cause, corrective actions) recorded after
  any Sev event. This is a proposal for adoption, not an existing org process.

## 9. Resiliency Testing (RESILIENCY-14, Q5=A) — scenarios captured now, executed in Operations
- Restore new tables from backup into a scratch DB; verify assertion verification still works.
- Cache-miss / Redis-down: public reads fall back to DB (verify no errors, only slower).
- Aggregator downtime then catch-up: confirm no double counting (watermark + idempotent upsert).
- Partition maintenance: confirm inserts near month boundaries land in correct/DEFAULT partition.

## 10. Accessibility (UX-1, Q5 WCAG AA)
- Semantic HTML, alt text for badge images, AA contrast, keyboard navigation and visible focus,
  labeled form controls. Public pages server-render meaningful content for crawlers/social + a11y.
  (Full WCAG validation requires manual assistive-tech testing + expert review — target, not cert.)
