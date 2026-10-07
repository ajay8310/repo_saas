# Build Instructions

Covers all units: U1 Badge Core, U2 Wallet, U3 Public Directory + Analytics,
U4 Certificates & Issuer Signing — plus the pre-existing platform.

## Prerequisites
- Docker Desktop running (the stack runs in containers; no local Python/Node needed).
- Docker CLI: `C:\Program Files\Docker\Docker\resources\bin\docker.exe` (Windows).

## Backend (Python 3.12 / FastAPI)

### Via Docker Compose (recommended)
```bash
docker compose up -d           # builds api/worker/beat images, starts db/redis/localstack/clamav
docker compose ps              # all 7 services healthy/up
```

### Apply database migrations (through U3)
```bash
docker exec repo_as_saas-api-1 alembic upgrade head
docker exec repo_as_saas-api-1 alembic current     # expect: 007 (head)
```
Migration chain: 001 initial → 002 RLS → 003 webhook secret → 004 anchoring/consent →
**005 badges** → **006 certificates** → **007 badge analytics**.

### Reversibility check (each new migration)
```bash
docker exec repo_as_saas-api-1 sh -c "alembic downgrade -1 && alembic upgrade head"
```
Verified for 005, 006, 007 (upgrade → downgrade → upgrade clean).

### Lint / type-check (optional, matches CI)
```bash
docker exec repo_as_saas-api-1 ruff check app/
docker exec repo_as_saas-api-1 mypy app/
```

## Frontend (React + Vite + TypeScript)
```bash
docker start frontend          # runs npm install + vite dev server on :3000
docker exec frontend npx tsc --noEmit    # type-check — expect no output (clean)
```
Verified: `CLEAN_NO_ERRORS`.

## Celery worker + beat
Brought up by compose. Beat schedules include the new U3 job:
`badge-analytics-aggregation` every 120s (`app.tasks.badge_analytics.aggregate_badge_analytics`),
plus the U1 `bulk_issue_badges` task.

## Endpoints after build
- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/api/v1/docs`
- Frontend: `http://localhost:3000`
- Public directory: `http://localhost:3000/directory`

## Known build notes
- The DB role is least-privilege; the analytics aggregator enumerates tenants from the
  `tenants` table (no RLS-bypass needed).
- Partitioned tables (`badge_assertions`, `badge_events`) require UNIQUE indexes to include the
  partition key — handled in migration 005.
