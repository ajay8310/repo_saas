# Shared Infrastructure — Badge Feature

Components shared across U1, U2, U3 (documented so units don't duplicate or conflict).

## Shared database objects
- **`badge_events`** table: written by U1 (issued/revoked/verified/viewed), U2 (published), U3
  (shared); read by U3 aggregator. Created in the **U1 migration** (brought forward) so all units can
  emit from day one.
- **`badge_assertions`**: created in U1; read/updated by U2 (flags) and U3 (public reads).
- Partitions (assertions/events) are shared physical infra; one migration owns their creation +
  maintenance note.

## Shared Redis namespaces
- `obadge:assn:*`, `obadge:page:*`, `obadge:dir:*` (cache) — written/invalidated by U1/U2/U3.
- `ratelimit:ip:*` (per-IP throttle) — used by the public gateway (U3 routes + U1 public verify).
- `analytics:watermark` — owned by U3 aggregator.

## Shared S3
- `badges/{tenant_id}/{badge_class_id}` prefix — images uploaded in U1, served (presigned) by U3
  public pages.

## Shared services / helpers
- `BadgeEventService` (event append) — defined with U3's analytics but callable from U1/U2. To avoid a
  backward code dependency under design-all-then-code, its table lands in the U1 migration and the
  minimal `record()` helper is implemented early (U1), with aggregation/read added in U3.
- `OpenBadgesSerializer` — U1 helper reused by U3 sharing/public pages.

## Shared config keys
`PUBLIC_BASE_URL`, `BADGE_IMAGE_PREFIX`, `OBADGE_CACHE_TTL_SECONDS`, `PUBLIC_RATE_LIMIT_PER_IP`,
`ANALYTICS_AGG_INTERVAL_SECONDS`, `PRESIGNED_URL_TTL_SECONDS`.

## Public gateway (shared deployable)
- One `public-gateway` container serves all unauthenticated badge routes across units (U1 verify
  subset + U3 pages/directory). Shared per-IP throttle + cache.
