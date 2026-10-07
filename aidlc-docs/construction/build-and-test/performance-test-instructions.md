# Performance Test Instructions

Targets the scale-sensitive paths added by the Credly units.

## Hotspots & how to exercise them

### 1. Public verification (U1/U3) — read-heavy, unauthenticated
- Endpoint: `GET /api/v1/public/badges/assertions/{id}`
- Protections: per-IP fixed-window throttle + short-TTL (~60s) Redis cache.
- Load test (example with hey/k6): sustain N req/s for a public assertion; confirm cached responses
  are served without a DB hit after the first, and the per-IP limiter returns 429 past the window cap
  (`public_rate_limit_per_ip` / `public_rate_limit_window_seconds`).

### 2. Public directory keyset pagination (U3) — large-collection scan
- Endpoints: `GET /public/badges/directory/{tenant}`,
  `.../classes/{id}/earners?cursor=&limit=`.
- Pagination is keyset/seek on `(issued_at desc, id desc)` / `(created_at desc, id desc)`, sized for
  10M+ rows (BR-D3). Verify page latency stays flat as `offset`-equivalent depth grows (no OFFSET
  scan). Seed many assertions, page to the end with cursors, compare first-page vs deep-page latency.

### 3. Analytics aggregation (U3) — periodic batch
- Task: `app.tasks.badge_analytics.aggregate_badge_analytics` (beat 120s).
- Idempotent recompute of touched buckets using a Redis watermark; cold start reprocesses a bounded
  30-day window. Measure runtime as `badge_events` grows; confirm per-run cost tracks *new* events,
  not total history (watermark working).

### 4. Bulk badge issuance (U1)
- `POST /badges/bulk-issue` → Celery `bulk_issue_badges`; per-recipient independent issue.
- Measure throughput for a 10k-recipient batch; failures are isolated per record.

### 5. Certificate rendering (U4) — CPU/image
- `GET /badges/assertions/{id}/certificate` renders a PDF with photo + badge image + QR + signature.
- Measure p95 render time; images are fetched from S3 (presigned) and embedded. Consider caching
  rendered PDFs if render rate is high (not implemented — flagged).

## Suggested tooling
- `k6` or `hey` for HTTP load; `locust` for scripted multi-step flows.
- Watch Postgres `pg_stat_statements` for the directory and analytics queries; both are indexed
  (`ix_badge_assertions_public`, `ix_badge_analytics_tenant_day`, keyset-friendly orderings).

## Status
No automated performance suite is committed yet. The design choices above (cache, throttle, keyset
pagination, watermarked idempotent aggregation, pre-aggregated analytics reads) are the perf controls;
this file is the plan for load-validating them.
