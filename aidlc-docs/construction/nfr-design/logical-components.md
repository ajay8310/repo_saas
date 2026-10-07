# NFR Logical Components — Badge Feature

## Data-tier components
| Component | Type | Purpose |
|---|---|---|
| `badge_classes` | table | templates (RLS; indexed; pg_trgm) |
| `badge_assertions` | **RANGE(issued_at) partitioned** table | issued instances; composite PK (id, issued_at) + UNIQUE(id); RLS |
| `badge_events` | **RANGE(created_at) partitioned** table | analytics event stream; composite PK (id, created_at); RLS |
| `badge_analytics_daily` | table | daily rollup; UNIQUE(tenant, day, class); RLS |
| monthly partitions | table partitions | pre-created for assertions/events (like audit_logs) |

## Cache components (Redis)
| Key pattern | TTL | Invalidation |
|---|---|---|
| `obadge:assn:{credential_id}` | 60s | delete on revoke/unpublish/edit |
| `obadge:page:{credential_id}` | 60s | delete on revoke/unpublish |
| `obadge:dir:{tenant}:v{ver}:{cursor}` | 60s | bump `obadge:dir:ver:{tenant}` on catalog change |
| `ratelimit:ip:{route}:{ip}` | window | per-IP token bucket for public routes |
| `analytics:watermark` | persistent | last processed event marker for aggregator |

## Compute / task components
| Component | Type | Notes |
|---|---|---|
| `aggregate_badge_analytics` | Celery beat (~2 min) | idempotent upsert; watermark-driven |
| `bulk_issue_badges` | Celery task | independent per-row savepoints |
| per-IP throttle middleware/dep | FastAPI dependency | applied to public_badges routes |
| cache read-through/invalidation helper | service util | wraps assertion/page/directory reads |

## Routing components
- `badges` (auth: tenant_admin/issuer) · `wallet` (auth: beneficiary/OTP) ·
  `public_badges` (unauth + per-IP throttle + cache) · `badge_analytics` (auth: tenant_admin).

## Observability / health (RESILIENCY-05/06)
- New routes participate in the existing health surface.
- Metrics/log signals to add: aggregation lag (events behind watermark), badge-route error rate,
  cache hit ratio, per-IP 429 rate. Alerts route into the proposed IR process (RESILIENCY-15).

## Migration component
- `alembic/versions/005_badges.py`: create tables, partitions, RLS enable/force + `tenant_isolation`
  policies, indexes, and (reuse) any needed triggers. Reversible `downgrade()`.

## Dependency notes
- `badge_events` table created in the U1 migration (brought forward) so U1/U2 event emission works
  before U3's aggregation/read components exist.
