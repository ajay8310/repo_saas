# NFR Design Plan — All Units (U1, U2, U3)

Turn the approved NFRs into concrete design patterns + logical components. Two mandatory resiliency
decisions are included (RESILIENCY-14 testing approach, RESILIENCY-15 incident response). Answer the
questions, then tell me you're done.

## Methodology / Execution Checklist (run after approval)
- [x] nfr-design-patterns.md (partitioning, pagination, caching+invalidation, throttling, idempotent aggregation, resilience patterns, WCAG approach)
- [x] logical-components.md (indexes, cache keys, rate-limit buckets, partitions, Celery schedule, health)

## Pre-decided (from NFR Requirements)
- Targets 500ms/1s; partition from start (Q2=B); per-IP throttle; short-TTL cache w/ invalidation;
  WCAG 2.1 AA; Hypothesis for PBT; Backup&Restore DR; single-region MZ.

---

## Questions

## Question 1  (partition key — the flagged decision)
How should `badge_assertions` (and `badge_events`) be partitioned?

A) RANGE by `issued_at` monthly (mirrors existing `audit_logs`; composite PK `(id, issued_at)`; time-series friendly; old data ages out cleanly)

B) HASH by `tenant_id` (even distribution across tenants; composite PK `(id, tenant_id)`; better for tenant-skewed workloads)

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A (delegated to AI judgment)

## Question 2  (composite PK vs id-only + credential link)
Given partitioning needs the partition column in the PK, and assertion.id == credential_id (== documents.id):

A) Composite PK on badge_assertions that INCLUDES the partition column; keep a UNIQUE index on `id` alone so the credential_id link and public URL stay by single id

B) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A (delegated)

## Question 3  (cache invalidation granularity)
Short-TTL cache invalidation on revoke/unpublish/edit:

A) Targeted key delete (invalidate exactly the affected assertion/page keys)

B) TTL-only (just let ~60s TTL expire; accept brief staleness)

C) Recommend for me

X) Other (please describe after [Answer]: tag below)

[Answer]: A (delegated)

## Question 4  (RESILIENCY-15 — incident response)
No formal IR process exists. For this feature:

A) Propose a lightweight IR + Correction-of-Errors (COE) process (alert → triage → mitigate → COE note) and wire new-feature alerts into it

B) Defer — rely on existing platform ops (if any) and revisit in Operations

X) Other (please describe after [Answer]: tag below)

[Answer]: A (delegated)

## Question 5  (RESILIENCY-14 — resiliency testing approach)
How to validate resiliency (backup/restore of new tables, cache-miss behavior, partition maintenance)?

A) Propose a DR test checklist now, execute in Operations phase (capture scenarios at design time)

B) Use existing DR testing practice (reference it)

C) Defer entirely to Operations

X) Other (please describe after [Answer]: tag below)

[Answer]: A (delegated)
