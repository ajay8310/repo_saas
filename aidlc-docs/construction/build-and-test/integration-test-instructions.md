# Integration Test Instructions

Integration tests exercise the full stack (PostgreSQL + RLS, Redis, S3 via
LocalStack, Celery) and the interactions between units. They require the compose
stack up and migrations applied through `007`.

## Prerequisites
```bash
docker compose up -d
docker exec repo_as_saas-api-1 alembic upgrade head
```

## Run integration tests (marker-based)
```bash
docker exec repo_as_saas-api-1 python -m pytest -m integration -q
```

## Cross-unit flows to verify (manual or scripted via the live API)
Use Swagger at `http://localhost:8000/api/v1/docs` or curl with a bearer token.

### U1 → U2 → U4 → U3 end-to-end
1. **Issuer profile + badge class** (U1): `PUT /badges/issuer-profile`, `POST /badges/classes`,
   `POST /badges/classes/{id}/image`, `PUT /badges/classes/{id}/template` (U4).
2. **Issue** (U1): `POST /badges/issue` → assertion id. Verify a `badge_events` `issued` row.
3. **Recipient photo** (U4): `POST /badges/assertions/{id}/photo`.
4. **Certificate** (U4): `GET /badges/assertions/{id}/certificate` → PDF `%PDF-`; issuer-signed
   (signature in metadata), QR → public verify URL. `GET /wallet/{id}/certificate` as the earner.
5. **Wallet** (U2): `GET /wallet`, `POST /wallet/{id}/public {public:true}` → `badge_events`
   `published`. `DELETE /wallet/{id}` → `hidden=true,public=false` but still verifiable.
6. **Public** (U3): `GET /api/v1/public/badges/assertions/{id}` (200 with recipient photo URL when
   public), `GET /api/v1/public/badges/directory/{tenant}`, `.../classes/{id}/earners` (masked),
   `GET /api/v1/public/badges/assertions/{id}/share?channel=linkedin` → `badge_events` `shared`.
7. **Analytics** (U3): wait ~2 min (or trigger the task) then `GET /badge-analytics/overview`,
   `/ranking`. Confirm counts reflect the events above.

### Tenant isolation (RLS) — must hold for every new table
- Tenant A cannot read tenant B's `badge_classes`, `badge_assertions`, `badge_events`,
  `badge_analytics_daily`. Verify via two tenants' tokens hitting the same ids → 404/empty.

### Trigger analytics aggregation on demand
```bash
docker exec repo_as_saas-worker-1 \
  python -c "from app.tasks.badge_analytics import aggregate_badge_analytics as t; print(t.apply().result)"
```
Idempotence: run twice; `badge_analytics_daily` counts are identical (no double counting), and the
tenant-wide (class=NULL) row equals the sum of per-class rows for each metric.

## Status
Integration suite scaffolding exists under `tests/integration`. The cross-unit flows above were
exercised against the live stack during construction (routes confirmed in OpenAPI; migrations applied;
aggregation task registered on the 120s beat).
